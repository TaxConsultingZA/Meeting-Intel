"""Shared test isolation settings."""
import pytest


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
