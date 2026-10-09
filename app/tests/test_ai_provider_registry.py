"""Server-only adapter preparation and local factories; no credentials or I/O."""
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.ai import registry
from app.ai.policy import (
    AIFeature, ProcessingMode, ProcessingPolicy, ProviderCapabilities, RouteKind,
)
from app.ai.providers import (
    LocalMockProvider, ProviderDescriptor, ProviderIdentity, TranscriptOnlyProvider,
)


FEATURES = frozenset({AIFeature.SUMMARY, AIFeature.ACTION_ITEMS})


def local(**changes):
    values = dict(provider_id="local.mock", route_kind=RouteKind.LOCAL_MOCK,
                  enabled=True, approved=True, contract_versions=frozenset({"1.0"}),
                  features=FEATURES)
    values.update(changes)
    return ProviderDescriptor(capabilities=ProviderCapabilities(**values), local_factory="mock")


def policy(*ids, **changes):
    values = dict(mode=ProcessingMode.CAPABILITY, allowed_provider_ids=ids,
                  required_features=FEATURES)
    values.update(changes)
    return ProcessingPolicy(**values)


@pytest.mark.parametrize("implementation,provider_type", [
    ("mock", LocalMockProvider), ("transcript_only", TranscriptOnlyProvider),
])
def test_existing_configuration_selects_compatible_local_factory(implementation, provider_type):
    prepared, configured, requested = registry.local_runtime_configuration(implementation)
    provider = prepared.create(configured, requested_provider_id=requested)
    assert type(provider) is provider_type
    assert provider.identity.provider_id == requested


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"approved": False}, {"contract_versions": frozenset({"2.0"})},
    {"features": frozenset({AIFeature.SUMMARY})},
])
def test_denied_local_route_does_not_construct_provider(monkeypatch, changes):
    factory = MagicMock(identity=LocalMockProvider.identity)
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"mock": factory})
    prepared = registry.ProviderRegistry((local(**changes),))
    with pytest.raises(registry.ProviderRegistryError):
        prepared.create(policy("local.mock"), requested_provider_id="local.mock")
    factory.assert_not_called()


@pytest.mark.parametrize("configured", [
    policy(), policy("other"), policy("local.mock", mode=ProcessingMode.DISABLED),
    policy("local.mock", mode=ProcessingMode.PRIVACY),
])
def test_policy_denial_prevents_provider_construction(monkeypatch, configured):
    factory = MagicMock(identity=LocalMockProvider.identity)
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"mock": factory})
    prepared = registry.ProviderRegistry((local(),))
    with pytest.raises(registry.ProviderRegistryError):
        prepared.create(configured, requested_provider_id="local.mock")
    factory.assert_not_called()


@pytest.mark.parametrize("provider_id", ["gemini.prepared", "businessai.prepared", "vendor.prepared"])
@pytest.mark.parametrize("kind", [RouteKind.CLOUD, RouteKind.WORKSPACE])
def test_external_preparations_cannot_execute_even_when_policy_allows(monkeypatch, provider_id, kind):
    # These names have no routing semantics and establish no vendor guarantees.
    descriptor = ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id=provider_id, route_kind=kind, enabled=True, approved=True,
        contract_versions=frozenset({"1.0"}), features=FEATURES,
        workspace_id="test-workspace" if kind == RouteKind.WORKSPACE else None,
    ), credential_reference="TEST_SERVER_CREDENTIAL")
    factory = MagicMock(identity=LocalMockProvider.identity)
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"mock": factory})
    prepared = registry.ProviderRegistry((descriptor, local()))
    configured = policy(provider_id, "local.mock", allowed_workspace_ids=frozenset({"test-workspace"}))
    with pytest.raises(registry.ProviderRegistryError):
        prepared.create(configured, requested_provider_id=provider_id)
    factory.assert_not_called()  # No external construction or fallback to local.
    assert not hasattr(descriptor, "process")


def test_external_preparation_defaults_disabled_and_unapproved():
    descriptor = ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id="vendor.prepared", route_kind=RouteKind.CLOUD))
    assert not descriptor.capabilities.enabled and not descriptor.capabilities.approved
    assert descriptor.model_id is None and descriptor.local_factory is None


def test_disabled_request_does_not_fall_back_to_permitted_transcript_route(monkeypatch):
    factory = MagicMock(identity=TranscriptOnlyProvider.identity)
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"transcript_only": factory})
    transcript = ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id="local.transcript_only", route_kind=RouteKind.LOCAL_TRANSCRIPT,
        enabled=True, approved=True, contract_versions=frozenset({"1.0"}),
    ), local_factory="transcript_only")
    prepared = registry.ProviderRegistry((local(enabled=False), transcript))
    configured = policy("local.mock", "local.transcript_only")
    with pytest.raises(registry.ProviderRegistryError):
        prepared.create(configured, requested_provider_id="local.mock")
    factory.assert_not_called()


def test_duplicate_descriptors_fail_closed():
    with pytest.raises(registry.ProviderRegistryError):
        registry.ProviderRegistry((local(), local()))


def test_identity_mismatch_is_rejected_before_construction(monkeypatch):
    factory = MagicMock(identity=ProviderIdentity("wrong.identity"))
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"mock": factory})
    with pytest.raises(registry.ProviderRegistryError):
        registry.ProviderRegistry((local(),)).create(policy("local.mock"), requested_provider_id="local.mock")
    factory.assert_not_called()


def test_constructed_identity_must_match_selected_descriptor(monkeypatch):
    factory = MagicMock(identity=LocalMockProvider.identity)
    factory.return_value.identity = ProviderIdentity("wrong.identity")
    monkeypatch.setattr(registry, "_LOCAL_FACTORIES", {"mock": factory})
    with pytest.raises(registry.ProviderRegistryError):
        registry.ProviderRegistry((local(),)).create(policy("local.mock"), requested_provider_id="local.mock")
    factory.assert_called_once()


def test_external_factory_binding_is_rejected_even_if_validation_was_bypassed():
    capabilities = ProviderCapabilities(provider_id="vendor.prepared", route_kind=RouteKind.CLOUD)
    with pytest.raises(ValidationError):
        ProviderDescriptor(capabilities=capabilities, local_factory="mock")
    forged = ProviderDescriptor.model_construct(capabilities=capabilities, local_factory="mock")
    with pytest.raises(registry.ProviderRegistryError):
        registry.ProviderRegistry((forged,))


@pytest.mark.parametrize("reference", ["https://credential.invalid/value", "inline value", "", "KEY=value"])
def test_credential_reference_accepts_only_server_binding_identifiers(reference):
    with pytest.raises(ValidationError):
        ProviderDescriptor(capabilities=ProviderCapabilities(
            provider_id="vendor.prepared", route_kind=RouteKind.CLOUD), credential_reference=reference)


def test_credential_reference_is_not_resolved_or_serialized(monkeypatch):
    descriptor = ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id="vendor.prepared", route_kind=RouteKind.CLOUD), credential_reference="TEST_SERVER_CREDENTIAL")
    assert "TEST_SERVER_CREDENTIAL" not in repr(descriptor)
    assert "credential_reference" not in descriptor.model_dump()
    assert "TEST_SERVER_CREDENTIAL" not in descriptor.model_dump_json()
    # No credential resolver exists and registry construction does not read env.
    import os
    monkeypatch.setattr(os, "getenv", lambda *args: pytest.fail("Credential resolution attempted"))
    registry.ProviderRegistry((descriptor,))


def test_invalid_policy_is_reported_as_safe_configuration_failure():
    forged = policy("local.mock").model_copy(update={"allowed_provider_ids": ("local.mock", "local.mock")})
    with pytest.raises(registry.ProviderRegistryError) as exc:
        registry.ProviderRegistry((local(),)).create(forged, requested_provider_id="local.mock")
    assert str(exc.value) == "configuration"


def test_model_and_prompt_are_optional_server_config_not_vendor_defaults():
    descriptor = ProviderDescriptor(capabilities=ProviderCapabilities(
        provider_id="vendor.prepared", route_kind=RouteKind.CLOUD),
        model_id="configured-model", prompt_version="configured-prompt")
    assert descriptor.model_id == "configured-model"
    assert descriptor.prompt_version == "configured-prompt"
    assert descriptor.local_factory is None


@pytest.mark.parametrize("changes", [
    {"credential_reference": "TEST_SERVER_CREDENTIAL"}, {"model_id": "configured-model"},
    {"local_factory": "transcript_only"},
])
def test_local_route_cannot_receive_external_configuration_or_wrong_factory(changes):
    with pytest.raises(ValidationError):
        ProviderDescriptor.model_validate({**local().model_dump(), **changes})
