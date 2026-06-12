"""Tests for app/config.py — Settings and URL normalisation."""
import pytest
from unittest.mock import patch


def _make_settings(**overrides):
    """Return a Settings instance with minimal required fields plus any overrides.

    Uses _env_file=None so the project's .env on disk doesn't bleed into tests.
    """
    import os
    from app.config import Settings
    # Temporarily clear any env vars that might come from the real .env
    env_backup = {}
    for key in ("EMAILS_ENABLED", "AUTO_SEND_EMAIL", "DATABASE_URL"):
        env_backup[key] = os.environ.pop(key, None)

    defaults = dict(
        tenant_id="t", client_id="c", client_secret="s",
        database_url="postgresql+asyncpg://u:p@localhost/db",
    )
    defaults.update(overrides)
    try:
        return Settings(_env_file=None, **defaults)
    finally:
        for key, val in env_backup.items():
            if val is not None:
                os.environ[key] = val


class TestAsyncpgUrl:
    def test_already_asyncpg_passthrough(self):
        s = _make_settings(database_url="postgresql+asyncpg://u:p@h/db")
        assert s.asyncpg_url == "postgresql+asyncpg://u:p@h/db"

    def test_postgres_prefix_normalised(self):
        s = _make_settings(database_url="postgres://u:p@h/db")
        assert s.asyncpg_url == "postgresql+asyncpg://u:p@h/db"

    def test_postgresql_prefix_normalised(self):
        s = _make_settings(database_url="postgresql://u:p@h/db")
        assert s.asyncpg_url == "postgresql+asyncpg://u:p@h/db"

    def test_unknown_prefix_passthrough(self):
        s = _make_settings(database_url="sqlite:///local.db")
        assert s.asyncpg_url == "sqlite:///local.db"


class TestEmailsEnabledDefault:
    def test_default_is_true(self):
        s = _make_settings()
        assert s.emails_enabled is True

    def test_can_be_disabled(self):
        s = _make_settings(emails_enabled=False)
        assert s.emails_enabled is False


class TestAutoSendEmailDefault:
    def test_default_is_false(self):
        s = _make_settings()
        assert s.auto_send_email is False
