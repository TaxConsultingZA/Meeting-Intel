from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_calendar_sync_runs_when_onedrive_reconcile_is_disabled(monkeypatch):
    from app import main
    from app.workers import reconcile, sync_microsoft

    calendar_sync = AsyncMock(return_value=3)
    onedrive_reconcile = AsyncMock(return_value=2)
    monkeypatch.setattr(sync_microsoft, "sync_calendar_events", calendar_sync)
    monkeypatch.setattr(reconcile, "reconcile", onedrive_reconcile)
    monkeypatch.setattr(main.settings, "enable_auto_reconcile", False)

    assert await main._sync_microsoft_once() == (3, 0)
    calendar_sync.assert_awaited_once_with()
    onedrive_reconcile.assert_not_awaited()
