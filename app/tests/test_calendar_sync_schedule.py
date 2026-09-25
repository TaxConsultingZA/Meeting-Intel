from unittest.mock import AsyncMock
import asyncio

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


@pytest.mark.asyncio
async def test_reconcile_endpoint_reuses_inflight_task(monkeypatch):
    from app import main

    started = asyncio.Event()
    release = asyncio.Event()

    async def reconcile():
        started.set()
        await release.wait()

    monkeypatch.setattr(main.settings, "reconcile_secret", "secret")
    monkeypatch.setattr(main, "_manual_reconcile_task", None)
    monkeypatch.setattr("app.workers.reconcile.reconcile", reconcile)

    first = await main.trigger_reconcile("secret")
    await started.wait()
    second = await main.trigger_reconcile("secret")
    assert first == second == {"status": "reconciliation started"}
    release.set()
    await main._manual_reconcile_task
    main._manual_reconcile_task = None


@pytest.mark.asyncio
async def test_lifespan_cancels_and_awaits_reconcile_task(monkeypatch):
    from app import main

    cancelled = asyncio.Event()

    async def loop():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main, "_init_db", AsyncMock())
    monkeypatch.setattr(main, "_seed_business_units", AsyncMock())
    monkeypatch.setattr(main, "_seed_admin_users", AsyncMock())
    monkeypatch.setattr(main, "_reconcile_loop", loop)

    async with main._lifespan(None):
        await asyncio.sleep(0)
    assert cancelled.is_set()
