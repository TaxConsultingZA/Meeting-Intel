from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def harness(monkeypatch):
    from app.workers import reconcile as worker
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = SimpleNamespace(graph_drive_id=None)
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker, "_get_subscribed_upns", AsyncMock(return_value={"owner@example.com"}))
    monkeypatch.setattr(worker.graph, "get_user_drive_id", AsyncMock(return_value="drive"))
    scan = AsyncMock(return_value=[{"id": "bad", "name": "bad.mp4"}, {"id": "good", "name": "good.mp4"}])
    monkeypatch.setattr(worker.graph, "list_recordings_folder", scan)
    status = AsyncMock()
    monkeypatch.setattr(worker, "record_sync_result", status)
    return worker, session, scan, status


async def test_single_file_failure_continues_then_retry_is_idempotent(harness, monkeypatch, capsys):
    worker, session, scan, status = harness
    stored = set()
    fail_once = True

    async def claim(db, item_id, *args, **kwargs):
        nonlocal fail_once
        if item_id == "bad" and fail_once:
            fail_once = False
            raise RuntimeError("secret-token-must-not-be-logged")
        if item_id in stored:
            return False
        stored.add(item_id)
        return True

    monkeypatch.setattr(worker, "claim_item", claim)
    assert await worker.reconcile() == 1
    assert "incomplete" in str(status.await_args.kwargs["error"])
    assert stored == {"good"}
    assert await worker.reconcile() == 1
    assert await worker.reconcile() == 0
    assert stored == {"bad", "good"}
    assert status.await_args.kwargs["error"] is None
    scan.assert_awaited_with("drive", strict=True)
    output = capsys.readouterr().out
    assert "item=bad" in output
    assert "secret-token" not in output


async def test_graph_failure_does_not_claim_or_record_success(harness, monkeypatch):
    worker, session, scan, status = harness
    scan.side_effect = RuntimeError("OneDrive discovery incomplete")
    claim = AsyncMock()
    monkeypatch.setattr(worker, "claim_item", claim)
    assert await worker.reconcile() == 0
    claim.assert_not_awaited()
    assert status.await_count == 1
    assert status.await_args.kwargs["error"] is not None


async def test_graph_failure_diagnostic_keeps_status_without_secret_url(harness, monkeypatch):
    import httpx
    worker, session, scan, status = harness
    response = httpx.Response(403, request=httpx.Request("GET", "https://graph.microsoft.com/?token=SECRET"))
    scan.side_effect = httpx.HTTPStatusError("token=SECRET", request=response.request, response=response)
    monkeypatch.setattr(worker, "claim_item", AsyncMock())
    assert await worker.reconcile() == 0
    diagnostic = str(status.await_args.kwargs["error"])
    assert "HTTP 403" in diagnostic
    assert "SECRET" not in diagnostic


async def test_success_is_recorded_after_last_claim(harness, monkeypatch):
    worker, session, scan, status = harness
    events = []

    async def claim(*args, **kwargs):
        events.append("claim")
        return True

    async def record(*args, **kwargs):
        events.append("success")

    monkeypatch.setattr(worker, "claim_item", claim)
    status.side_effect = record
    assert await worker.reconcile() == 2
    assert events == ["claim", "claim", "success"]
