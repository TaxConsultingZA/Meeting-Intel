from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


async def test_events_between_reuses_main_graph_token(monkeypatch):
    from app.graph import calendar_match

    get_token = MagicMock(return_value="cached-app-token")
    response = MagicMock()
    response.json.return_value = {"value": [{"id": "event-1"}]}
    response.raise_for_status = MagicMock()
    http = AsyncMock()
    http.get.return_value = response
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=http)
    context.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(calendar_match, "get_token", get_token)
    monkeypatch.setattr(calendar_match.httpx, "AsyncClient", MagicMock(return_value=context))

    result = await calendar_match.events_between(
        "alice@taxconsulting.co.za",
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 2, tzinfo=timezone.utc),
    )

    assert result == [{"id": "event-1"}]
    get_token.assert_called_once_with()
    _, kwargs = http.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer cached-app-token"
    response.raise_for_status.assert_called_once_with()
