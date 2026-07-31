"""Shared test isolation settings."""
import pytest


@pytest.fixture(autouse=True)
def isolate_auth_and_graph_modes(monkeypatch, request):
    """Use safe Mock auth, while Graph HTTP tests keep their mocked HTTP path."""
    from app.graph import client
    from app.api import deps

    graph_impl = "microsoft" if request.path.name == "test_graph_client.py" else "mock"
    monkeypatch.setattr(client.settings, "graph_impl", graph_impl)
    monkeypatch.setattr(deps.settings, "graph_impl", graph_impl)
    monkeypatch.setattr(deps.settings, "auth_mode", "mock")
