from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock


async def test_events_between_reuses_main_graph_token(monkeypatch):
    from app.graph import calendar_match, client

    get_token = MagicMock(return_value="cached-app-token")
    response = MagicMock()
    response.json.return_value = {"value": [{"id": "event-1"}]}
    response.raise_for_status = MagicMock()
    http = AsyncMock()
    http.get.return_value = response
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=http)
    context.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
    monkeypatch.setattr(client, "get_token", get_token)
    monkeypatch.setattr(client.httpx, "AsyncClient", MagicMock(return_value=context))

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


async def test_enrichment_calendar_reads_later_pages_and_refuses_foreign_next_link(monkeypatch):
    import httpx
    import pytest
    import respx

    from app.graph import calendar_match, client

    monkeypatch.setattr(client.settings, "graph_impl", "microsoft")
    monkeypatch.setattr(client, "get_token", lambda: "offline-token")
    base = client.settings.graph_base
    start = datetime(2026, 8, 1, tzinfo=UTC)
    end = datetime(2026, 8, 2, tzinfo=UTC)
    with respx.mock:
        respx.get(f"{base}/users/attendee%40example.test/calendarView").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "first"}],
                "@odata.nextLink": f"{base}/calendar-page-2"}))
        page = respx.get(f"{base}/calendar-page-2").mock(
            return_value=httpx.Response(200, json={"value": [{"id": "later"}]}))
        rows = await calendar_match.events_between("attendee@example.test", start, end)
        assert [row["id"] for row in rows] == ["first", "later"]
        page.mock(return_value=httpx.Response(200, json={"value": [],
            "@odata.nextLink": "https://untrusted.example/page"}))
        with pytest.raises(RuntimeError, match="Invalid Calendar pagination"):
            await calendar_match.events_between("attendee@example.test", start, end)
