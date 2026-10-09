"""Staging extraction configuration must match the local-only bridge."""
import pytest
from pydantic import ValidationError

from app.config import Settings


def settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_staging_default_is_transcript_only(monkeypatch):
    monkeypatch.delenv("EXTRACTOR_IMPL", raising=False)
    assert settings().extractor_impl == "transcript_only"


@pytest.mark.parametrize("implementation", ["transcript_only", "mock"])
def test_staging_accepts_supported_local_configuration(monkeypatch, implementation):
    monkeypatch.setenv("EXTRACTOR_IMPL", implementation)
    assert settings().extractor_impl == implementation


@pytest.mark.parametrize("implementation", ["gemini", "azure_openai", "businessai", "unknown"])
def test_staging_rejects_external_or_unknown_configuration(monkeypatch, implementation):
    monkeypatch.setenv("EXTRACTOR_IMPL", implementation)
    with pytest.raises(ValidationError) as error:
        settings(gemini_enabled=True)
    assert any(item["loc"] == ("extractor_impl",) for item in error.value.errors())
