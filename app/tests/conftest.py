"""Shared test isolation settings."""
import pytest


@pytest.fixture(autouse=True)
def use_real_graph_http_path_for_unit_tests(monkeypatch):
    """Graph client unit tests mock HTTP themselves; do not use local demo data."""
    from app.graph import client

    monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
