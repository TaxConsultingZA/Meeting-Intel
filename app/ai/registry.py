"""Policy-gated local factories and one explicitly configured chat adapter.

Other external preparations remain inert. No dynamic imports, logging or retry.
"""
from types import MappingProxyType

from pydantic import ValidationError

from .businessai import BusinessAIConfig, BusinessAIProvider, PROMPT_VERSION, PROVIDER_ID
from .contracts import FailureCode
from .policy import (
    AIFeature, ProcessingMode, ProcessingPolicy, ProviderCapabilities, RouteKind,
    select_provider,
)
from .providers import (
    AIProvider, LocalMockProvider, ProviderDescriptor, ProviderFailure,
    ProviderIdentity, TranscriptOnlyProvider,
)


class ProviderRegistryError(ProviderFailure):
    """Safe configuration failure, without policy/credential/response content."""

    def __init__(self):
        super().__init__(FailureCode.CONFIGURATION)


_LOCAL_FACTORIES = MappingProxyType({
    "transcript_only": TranscriptOnlyProvider,
    "mock": LocalMockProvider,
})


class ProviderRegistry:
    def __init__(self, descriptors: tuple[ProviderDescriptor, ...]):
        try:
            # Revalidate even model_construct/model_copy values before selection.
            prepared = tuple(ProviderDescriptor.model_validate({
                **descriptor.model_dump(),
                "credential_reference": descriptor.credential_reference,
            }) for descriptor in descriptors)
            ids = [descriptor.capabilities.provider_id for descriptor in prepared]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate provider identity")
        except (ValidationError, ValueError, AttributeError, TypeError):
            raise ProviderRegistryError() from None
        self._descriptors = MappingProxyType(dict(zip(ids, prepared)))

    def create(self, policy: ProcessingPolicy, *, requested_provider_id: str,
               businessai_config: BusinessAIConfig | None = None) -> AIProvider:
        """Select one explicit route before constructing a configured provider.

        External descriptors need the exact reviewed BusinessAI configuration.
        Denial or failure never causes selection of another descriptor.
        """
        try:
            selection = select_provider(policy, tuple(
                descriptor.capabilities for descriptor in self._descriptors.values()
            ), requested_provider_id=requested_provider_id)
        except (ValidationError, ValueError, AttributeError, TypeError):
            raise ProviderRegistryError() from None
        if not selection.permitted:
            raise ProviderRegistryError()
        descriptor = self._descriptors[selection.provider_id]
        if businessai_config is not None and descriptor.capabilities.provider_id == PROVIDER_ID:
            expected_identity = ProviderIdentity(PROVIDER_ID, descriptor.model_id, descriptor.prompt_version)
            if (descriptor.capabilities.route_kind != RouteKind.CLOUD
                    or descriptor.capabilities.automatic_fallback_allowed
                    or expected_identity != ProviderIdentity(PROVIDER_ID, businessai_config.model_id, PROMPT_VERSION)):
                raise ProviderRegistryError()
            try:
                provider = BusinessAIProvider(businessai_config)
            except ProviderFailure:
                raise ProviderRegistryError() from None
            if provider.identity != expected_identity:
                raise ProviderRegistryError()
            return provider
        if descriptor.capabilities.route_kind not in {
            RouteKind.LOCAL_TRANSCRIPT, RouteKind.LOCAL_MOCK,
        } or descriptor.local_factory is None:
            raise ProviderRegistryError()
        factory = _LOCAL_FACTORIES[descriptor.local_factory]
        expected_identity = ProviderIdentity(
            descriptor.capabilities.provider_id, descriptor.model_id, descriptor.prompt_version,
        )
        # Check the binding before construction and again before returning it.
        if factory.identity != expected_identity:
            raise ProviderRegistryError()
        try:
            provider = factory()
            if provider.identity != expected_identity:
                raise ValueError("Provider identity mismatch")
        except Exception:
            raise ProviderRegistryError() from None
        return provider


def businessai_runtime_configuration(config: BusinessAIConfig) -> tuple[ProviderRegistry, ProcessingPolicy, str]:
    """Pin the sole external route and model; configuration never selects a backup."""
    features = frozenset({AIFeature.SUMMARY, AIFeature.ACTION_ITEMS})
    descriptor = ProviderDescriptor(
        capabilities=ProviderCapabilities(
            provider_id=PROVIDER_ID, route_kind=RouteKind.CLOUD,
            enabled=config.enabled, approved=config.enabled,
            contract_versions=frozenset({"1.0"}), features=features,
            automatic_fallback_allowed=False,
        ), model_id=config.model_id or None, prompt_version=PROMPT_VERSION,
    )
    policy = ProcessingPolicy(mode=ProcessingMode.CAPABILITY,
                              allowed_provider_ids=(PROVIDER_ID,), required_features=features)
    return ProviderRegistry((descriptor,)), policy, PROVIDER_ID


def local_runtime_configuration(implementation: str) -> tuple[ProviderRegistry, ProcessingPolicy, str]:
    """Translate existing server settings to explicit local policy; no new settings.

    No external preparations are registered by default. Vendor names/models never
    affect routing. Future descriptors must be provided by trusted backend code.
    """
    routes = (
        ProviderDescriptor(capabilities=ProviderCapabilities(
            provider_id=TranscriptOnlyProvider.identity.provider_id,
            route_kind=RouteKind.LOCAL_TRANSCRIPT, enabled=True, approved=True,
            contract_versions=frozenset({"1.0"}), cloud_forwarding_allowed=False,
            automatic_fallback_allowed=False,
        ), local_factory="transcript_only"),
        ProviderDescriptor(capabilities=ProviderCapabilities(
            provider_id=LocalMockProvider.identity.provider_id,
            route_kind=RouteKind.LOCAL_MOCK, enabled=True, approved=True,
            contract_versions=frozenset({"1.0"}),
            features=frozenset({AIFeature.SUMMARY, AIFeature.ACTION_ITEMS}),
            cloud_forwarding_allowed=False, automatic_fallback_allowed=False,
        ), local_factory="mock"),
    )
    configuration = {
        "transcript_only": (routes[0], ProcessingMode.DISABLED, frozenset()),
        "mock": (routes[1], ProcessingMode.CAPABILITY,
                 frozenset({AIFeature.SUMMARY, AIFeature.ACTION_ITEMS})),
    }
    if implementation not in configuration:
        raise ProviderRegistryError()
    selected, mode, required_features = configuration[implementation]
    requested_id = selected.capabilities.provider_id
    policy = ProcessingPolicy(mode=mode, allowed_provider_ids=(requested_id,),
                              required_features=required_features)
    return ProviderRegistry(routes), policy, requested_id
