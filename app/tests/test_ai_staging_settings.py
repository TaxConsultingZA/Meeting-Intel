"""Staging defaults stay local; BusinessAI needs a separate explicit opt-in."""
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


@pytest.mark.parametrize("implementation", ["gemini", "azure_openai", "unknown"])
def test_staging_rejects_external_or_unknown_configuration(monkeypatch, implementation):
    monkeypatch.setenv("EXTRACTOR_IMPL", implementation)
    with pytest.raises(ValidationError) as error:
        settings(gemini_enabled=True)
    assert any(item["loc"] == ("extractor_impl",) for item in error.value.errors())


def test_businessai_selection_alone_does_not_enable_it(monkeypatch):
    monkeypatch.setenv("EXTRACTOR_IMPL", "businessai")
    configured = settings()
    assert not configured.businessai_enabled
    assert not configured.businessai_chat_url and not configured.businessai_model
    assert not configured.businessai_api_key.get_secret_value()
