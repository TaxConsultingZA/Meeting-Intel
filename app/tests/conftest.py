"""Shared test isolation settings."""
import os
import socket
import sys
import asyncio

import pytest

# Set harmless process-local values BEFORE test collection imports the app.
# Never read a production database URL or credential into a test client.
for _name, _value in {
    "DATABASE_URL": "postgresql+asyncpg://offline:offline@127.0.0.1:1/offline_tests",
    "TENANT_ID": "offline-tenant", "CLIENT_ID": "offline-client",
    "CLIENT_SECRET": "offline-secret",
    "AUTH_MICROSOFT_ENTRA_ID_TENANT_ID": "offline-tenant",
    "AUTH_MICROSOFT_ENTRA_ID_ID": "offline-client",
    "AUTH_MICROSOFT_ENTRA_ID_SECRET": "offline-secret",
    "ASSEMBLYAI_API_KEY": "", "GEMINI_API_KEY": "", "GEMINI_ENABLED": "false",
    "AZURE_OPENAI_KEY": "", "EMAILS_ENABLED": "false",
    "ENABLE_AUTO_RECONCILE": "false", "AUTO_SEND_EMAIL": "false",
}.items():
    os.environ[_name] = _value


def _deny_network(*args, **kwargs):
    raise AssertionError("Offline tests prohibit real network access; mock the transport")


def pytest_sessionstart(session):
    # Session-wide (including collection), not merely after fixtures start.
    session._offline_guard = pytest.MonkeyPatch()
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        # Windows asyncio builds its wake-up socketpair through stdlib's
        # loopback-only fallback. Allow exactly that call, not local DB/HTTP.
        fallback = getattr(socket, "_fallback_socketpair", None)
        if (fallback and sys._getframe(1).f_code is fallback.__code__
                and address[0] in ("127.0.0.1", "::1")):
            return original_connect(sock, address)
        return _deny_network()

    session._offline_guard.setattr(socket.socket, "connect", guarded_connect)
    for name in ("connect_ex", "sendto"):
        session._offline_guard.setattr(socket.socket, name, _deny_network)
    session._offline_guard.setattr(socket, "create_connection", _deny_network)
    session._offline_guard.setattr(socket, "getaddrinfo", _deny_network)
    session._offline_guard.setattr(asyncio.BaseEventLoop, "create_connection", _deny_network)
    if hasattr(asyncio, "ProactorEventLoop"):
        session._offline_guard.setattr(asyncio.ProactorEventLoop, "sock_connect", _deny_network)


def pytest_sessionfinish(session, exitstatus):
    session._offline_guard.undo()


@pytest.fixture(autouse=True)
def isolate_auth_and_graph_modes(monkeypatch, request):
    """Guarantee ordinary tests cannot consume any paid external API quota."""
    from app.graph import client
    from app.api import deps
    from app.pipeline import extract, transcribe

    graph_impl = "microsoft" if request.path.name == "test_graph_client.py" else "mock"
    monkeypatch.setattr(client.settings, "graph_impl", graph_impl)
    monkeypatch.setattr(deps.settings, "graph_impl", graph_impl)
    monkeypatch.setattr(deps.settings, "auth_mode", "mock")
    monkeypatch.setattr(extract.settings, "extractor_impl", "mock")
    monkeypatch.setattr(transcribe.settings, "transcriber_impl", "mock")
    monkeypatch.setattr(transcribe.settings, "assemblyai_api_key", "")
    monkeypatch.setattr(extract.settings, "emails_enabled", False)
    monkeypatch.setattr(extract.settings, "gemini_enabled", False)
