"""Pure, server-owned route policy. No transport, provider factory, or I/O."""
from enum import Enum

from pydantic import Field, model_validator

from .contracts import Contract


class ProcessingMode(str, Enum):
    DISABLED = "disabled"
    CAPABILITY = "capability"
    PRIVACY = "privacy"


class AIFeature(str, Enum):
    SUMMARY = "summary"
    ACTION_ITEMS = "action_items"
    DECISIONS = "decisions"


class RouteKind(str, Enum):
    LOCAL_TRANSCRIPT = "local_transcript"
    LOCAL_MOCK = "local_mock"
    CLOUD = "cloud"
    WORKSPACE = "workspace"


class ProviderCapabilities(Contract):
    # Describes an approved deployment route, not a vendor-wide guarantee.
    provider_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    route_kind: RouteKind
    enabled: bool = False
    approved: bool = False
    contract_versions: frozenset[str] = frozenset()
    features: frozenset[AIFeature] = frozenset()
    workspace_id: str | None = Field(default=None, min_length=1)
    privacy_verified: bool = False
    cloud_forwarding_allowed: bool = True
    automatic_fallback_allowed: bool = True

    @model_validator(mode="after")
    def valid_route(self):
        if self.workspace_id is not None and not self.workspace_id.strip():
            raise ValueError("Workspace identity must not be blank")
        if self.route_kind == RouteKind.LOCAL_TRANSCRIPT and self.features:
            raise ValueError("Transcript-only routes cannot advertise AI features")
        if self.route_kind in {RouteKind.LOCAL_TRANSCRIPT, RouteKind.LOCAL_MOCK}:
            if self.workspace_id is not None or self.privacy_verified:
                raise ValueError("Local test routes cannot claim verified workspace isolation")
        if self.route_kind == RouteKind.LOCAL_MOCK and not self.features.issubset(
            {AIFeature.SUMMARY, AIFeature.ACTION_ITEMS}
        ):
            raise ValueError("Local mock supports only summary and action items")
        return self


class ProcessingPolicy(Contract):
    policy_version: str = Field(default="1.0", min_length=1)
    mode: ProcessingMode = ProcessingMode.DISABLED
    # Order expresses administrator preference, never an automatic failover chain.
    allowed_provider_ids: tuple[str, ...] = ()
    allowed_workspace_ids: frozenset[str] = frozenset()
    required_features: frozenset[AIFeature] = frozenset()
    contract_version: str = Field(default="1.0", min_length=1)

    @model_validator(mode="after")
    def valid_policy(self):
        if len(set(self.allowed_provider_ids)) != len(self.allowed_provider_ids):
            raise ValueError("Allowed provider IDs must be unique")
        if any(not value.strip() for value in (*self.allowed_provider_ids, *self.allowed_workspace_ids)):
            raise ValueError("Policy identifiers must not be blank")
        return self


class SelectionFailure(str, Enum):
    NO_PERMITTED_PROVIDER = "no_permitted_provider"
    REQUESTED_PROVIDER_NOT_PERMITTED = "requested_provider_not_permitted"
    INVALID_REGISTRY = "invalid_registry"


class ProviderSelection(Contract):
    policy_version: str
    mode: ProcessingMode
    provider_id: str | None = None
    workspace_id: str | None = None
    failure: SelectionFailure | None = None

    @model_validator(mode="after")
    def consistent_outcome(self):
        if (self.provider_id is None) == (self.failure is None):
            raise ValueError("Selection must contain exactly one provider or failure")
        if self.failure is not None and self.workspace_id is not None:
            raise ValueError("Denied selection cannot contain a workspace")
        return self

    @property
    def permitted(self) -> bool:
        return self.failure is None

    @property
    def message(self) -> str:
        if self.permitted:
            return "A permitted processing route was selected."
        return "No permitted AI processing route is available. No processing was started. Ask an administrator to check the processing policy and route configuration."


def _permitted(policy: ProcessingPolicy, route: ProviderCapabilities) -> bool:
    if not route.enabled or not route.approved:
        return False
    if policy.contract_version not in route.contract_versions:
        return False
    if policy.mode == ProcessingMode.DISABLED:
        # Disabling AI must never disguise a missing analysis feature as success.
        return route.route_kind == RouteKind.LOCAL_TRANSCRIPT and not policy.required_features
    if route.route_kind == RouteKind.LOCAL_TRANSCRIPT:
        return False
    if not policy.required_features.issubset(route.features):
        return False
    if route.route_kind == RouteKind.WORKSPACE:
        if not route.workspace_id or route.workspace_id not in policy.allowed_workspace_ids:
            return False
    if policy.mode == ProcessingMode.PRIVACY:
        return (route.route_kind == RouteKind.WORKSPACE and route.privacy_verified
                and not route.cloud_forwarding_allowed and not route.automatic_fallback_allowed)
    return True


def select_provider(policy: ProcessingPolicy, capabilities: tuple[ProviderCapabilities, ...], *, requested_provider_id: str | None = None) -> ProviderSelection:
    """Validate trusted configuration and select an eligible route deterministically.

    Callers must obtain policy/capabilities from trusted server configuration,
    after existing authorization. This function never grants access, executes a
    provider, retries, or downgrades mode. Explicit requests never fall back.
    """
    policy = ProcessingPolicy.model_validate(policy.model_dump())
    routes = tuple(ProviderCapabilities.model_validate(route.model_dump()) for route in capabilities)

    def denied(code):
        return ProviderSelection(policy_version=policy.policy_version, mode=policy.mode, failure=code)

    if len({route.provider_id for route in routes}) != len(routes):
        return denied(SelectionFailure.INVALID_REGISTRY)
    registry = {route.provider_id: route for route in routes}
    candidates = (requested_provider_id,) if requested_provider_id is not None else policy.allowed_provider_ids
    for provider_id in candidates:
        route = registry.get(provider_id)
        if provider_id in policy.allowed_provider_ids and route and _permitted(policy, route):
            return ProviderSelection(policy_version=policy.policy_version, mode=policy.mode,
                                     provider_id=provider_id, workspace_id=route.workspace_id)
    return denied(SelectionFailure.REQUESTED_PROVIDER_NOT_PERMITTED if requested_provider_id is not None
                  else SelectionFailure.NO_PERMITTED_PROVIDER)
