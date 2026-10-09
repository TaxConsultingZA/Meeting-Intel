"""Pure policy tests; no provider instances, credentials, or network calls."""
import pytest
from pydantic import ValidationError

from app.ai.policy import (
    AIFeature, ProcessingMode, ProcessingPolicy, ProviderCapabilities,
    ProviderSelection, RouteKind, SelectionFailure, select_provider,
)


def route(provider_id="workspace.private", **overrides):
    values = dict(provider_id=provider_id, route_kind=RouteKind.WORKSPACE,
                  enabled=True, approved=True, contract_versions=frozenset({"1.0"}),
                  features=frozenset(AIFeature), workspace_id="org-private",
                  privacy_verified=True, cloud_forwarding_allowed=False,
                  automatic_fallback_allowed=False)
    values.update(overrides)
    return ProviderCapabilities(**values)


def policy(**overrides):
    values = dict(mode=ProcessingMode.PRIVACY, allowed_provider_ids=("workspace.private", "cloud.capability"),
                  allowed_workspace_ids=frozenset({"org-private"}), required_features=frozenset(AIFeature))
    values.update(overrides)
    return ProcessingPolicy(**values)


def cloud(**overrides):
    return route("cloud.capability", route_kind=RouteKind.CLOUD, workspace_id=None, **overrides)


def test_default_policy_and_capabilities_fail_closed():
    result = select_provider(ProcessingPolicy(), (ProviderCapabilities(provider_id="cloud", route_kind=RouteKind.CLOUD),))
    assert not result.permitted
    assert result.failure == SelectionFailure.NO_PERMITTED_PROVIDER
    assert "No processing was started" in result.message


def test_privacy_selects_verified_allowed_workspace():
    result = select_provider(policy(), (cloud(), route()))
    assert result.provider_id == "workspace.private"
    assert result.workspace_id == "org-private"
    assert result.policy_version == "1.0" and result.mode == ProcessingMode.PRIVACY


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"approved": False}, {"privacy_verified": False},
    {"cloud_forwarding_allowed": True}, {"automatic_fallback_allowed": True},
    {"workspace_id": None}, {"workspace_id": "other-org"},
    {"contract_versions": frozenset({"2.0"})}, {"features": frozenset({AIFeature.SUMMARY})},
])
def test_privacy_denials_never_downgrade_to_cloud(changes):
    result = select_provider(policy(), (route(**changes), cloud()))
    assert not result.permitted and result.provider_id is None


def test_capability_selection_uses_policy_order_not_registry_order():
    result = select_provider(policy(mode=ProcessingMode.CAPABILITY, allowed_provider_ids=("cloud.capability", "workspace.private")), (route(), cloud()))
    assert result.provider_id == "cloud.capability"


def test_explicit_request_cannot_override_policy_or_fall_back():
    result = select_provider(policy(), (route(), cloud()), requested_provider_id="cloud.capability")
    assert result.failure == SelectionFailure.REQUESTED_PROVIDER_NOT_PERMITTED
    assert not result.permitted


@pytest.mark.parametrize("provider_id", ["unknown", "", "not-allowed"])
def test_unknown_or_unallowed_explicit_provider_is_denied(provider_id):
    assert not select_provider(policy(), (route(),), requested_provider_id=provider_id).permitted


def test_empty_allowlist_never_selects_enabled_provider():
    assert not select_provider(policy(allowed_provider_ids=()), (route(),)).permitted


def test_duplicate_registry_fails_closed_even_for_valid_request():
    assert select_provider(policy(), (route(), route())).failure == SelectionFailure.INVALID_REGISTRY


def test_disabled_mode_allows_only_local_transcript_without_ai_features():
    local = route("local.transcript_only", route_kind=RouteKind.LOCAL_TRANSCRIPT,
                  features=frozenset(), workspace_id=None, privacy_verified=False)
    disabled = policy(mode=ProcessingMode.DISABLED, required_features=frozenset(),
                      allowed_provider_ids=("cloud.capability", "local.transcript_only"))
    assert select_provider(disabled, (cloud(), local)).provider_id == "local.transcript_only"
    assert not select_provider(policy(mode=ProcessingMode.DISABLED), (route(), cloud())).permitted
    assert not select_provider(disabled.model_copy(update={"required_features": frozenset({AIFeature.SUMMARY})}), (local,)).permitted


def test_analysis_does_not_silently_select_transcript_only():
    local = route("local.transcript_only", route_kind=RouteKind.LOCAL_TRANSCRIPT,
                  features=frozenset(), workspace_id=None, privacy_verified=False)
    assert not select_provider(policy(mode=ProcessingMode.CAPABILITY, required_features=frozenset(),
                                      allowed_provider_ids=("local.transcript_only",)), (local,)).permitted


@pytest.mark.parametrize("changes", [{"mode": "invalid"}, {"allowed_provider_ids": ("same", "same")}, {"extra": "value"}])
def test_invalid_policy_is_rejected(changes):
    with pytest.raises(ValidationError):
        policy(**changes)


def test_local_route_cannot_claim_ai_features():
    with pytest.raises(ValidationError):
        route(route_kind=RouteKind.LOCAL_TRANSCRIPT)


def test_selection_serializes_and_policy_is_immutable():
    source = policy()
    before = source.model_dump_json()
    result = select_provider(source, (route(),))
    assert ProviderSelection.model_validate_json(result.model_dump_json()) == result
    assert source.model_dump_json() == before
    with pytest.raises(ValidationError):
        source.mode = ProcessingMode.CAPABILITY


def test_provider_name_alone_never_establishes_privacy():
    unverified = route("businessai.workspace", privacy_verified=False)
    assert not select_provider(policy(allowed_provider_ids=("businessai.workspace",)), (unverified,)).permitted


def test_local_mock_is_capability_only_and_not_a_private_workspace():
    local = ProviderCapabilities(provider_id="local.mock", route_kind=RouteKind.LOCAL_MOCK,
        enabled=True, approved=True, contract_versions=frozenset({"1.0"}),
        features=frozenset({AIFeature.SUMMARY, AIFeature.ACTION_ITEMS}))
    configured = ProcessingPolicy(mode=ProcessingMode.CAPABILITY,
        allowed_provider_ids=("local.mock",), required_features=local.features)
    assert select_provider(configured, (local,), requested_provider_id="local.mock").permitted
    for mode in (ProcessingMode.DISABLED, ProcessingMode.PRIVACY):
        assert not select_provider(configured.model_copy(update={"mode": mode}), (local,),
                                   requested_provider_id="local.mock").permitted


@pytest.mark.parametrize("changes", [
    {"workspace_id": "claimed-workspace"}, {"privacy_verified": True},
    {"features": frozenset({AIFeature.DECISIONS})},
])
def test_mock_cannot_claim_workspace_privacy_or_decision_features(changes):
    with pytest.raises(ValidationError):
        ProviderCapabilities(provider_id="local.mock", route_kind=RouteKind.LOCAL_MOCK, **changes)
