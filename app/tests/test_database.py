"""Verify the actual driver boundary without contacting a database."""
import inspect
from unittest.mock import patch

import asyncpg
import pytest
from sqlalchemy import event

from app.database import create_database_engine, normalize_database_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_normalize(scheme):
    url = normalize_database_url(f"{scheme}://user:p%40ss@localhost/db?sslmode=require")
    assert url.startswith("postgresql+asyncpg://")
    from sqlalchemy.engine import make_url
    assert make_url(url).password == "p@ss"
    assert make_url(url).query["sslmode"] == "require"


@pytest.mark.parametrize("query,expected", [
    ("", "require"),
    ("?sslmode=require", "require"),
    ("?channel_binding=require", "require"),
    ("?sslmode=require&channel_binding=require", "require"),
    ("?sslmode=verify-full", "verify-full"),
    ("?sslmode=verify-ca", "verify-ca"),
])
async def test_actual_asyncpg_keywords(query, expected):
    engine = create_database_engine("postgres://user:dummy@localhost/db" + query)
    captured = {}

    class StopBeforeNetwork(Exception):
        pass

    def capture(dialect, connection_record, args, kwargs):
        captured.update(kwargs)
        raise StopBeforeNetwork

    event.listen(engine.sync_engine, "do_connect", capture)
    try:
        with pytest.raises(StopBeforeNetwork):
            async with engine.connect():
                pass
        assert "sslmode" not in captured
        assert "channel_binding" not in captured
        assert captured["ssl"] == expected
        inspect.signature(asyncpg.connect).bind(**captured)
        assert engine.pool._pre_ping is True
    finally:
        await engine.dispose()


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "invalid"])
def test_reject_tls_downgrade(mode):
    with pytest.raises(ValueError, match="TLS is required"):
        create_database_engine("postgres://user:dummy@localhost/db?sslmode=" + mode)


def test_api_factory_uses_shared_configuration():
    from app import db
    with patch.object(db, "create_database_engine") as factory:
        db._make_engine()
        factory.assert_called_once_with(db.get_settings().asyncpg_url)


def test_empty_url():
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        create_database_engine("")


async def test_preserve_other_connection_options():
    engine = create_database_engine(
        "postgresql://user:dummy@localhost/db?sslmode=require&command_timeout=15",
        connect_args={"server_settings": {"application_name": "regression"}},
    )
    assert engine.url.query == {"command_timeout": "15"}
    await engine.dispose()
