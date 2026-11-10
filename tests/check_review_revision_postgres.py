"""Opt-in concurrency check against the dedicated local release test database."""
import asyncio
import os
from uuid import uuid4

from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
if (url.drivername, url.host, url.port, url.username, url.database) != (
    "postgresql+asyncpg", "127.0.0.1", 53031, "synthetic", "admin_bu_release_check"
):
    raise RuntimeError("This check requires the dedicated local release test database.")

from fastapi import HTTPException, Response
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ActionItem, AuditEvent, Meeting, ProcessingState, RegisteredUser
from app.schemas import ActionItemEdit, ApproveMeetingIn, MeetingDecisionsIn, SpeakerMappingIn, TranscriptEdit
from app.api.reviews import approve, email_preview, edit_item, edit_transcript, save_meeting_decisions, save_speaker_mappings
from app.config import get_settings

if get_settings().emails_enabled or get_settings().auth_mode != "mock" or get_settings().graph_impl != "mock":
    raise RuntimeError("This check requires mock authentication and Graph with email disabled.")


async def main():
    meeting_id = uuid4()
    suffix = uuid4().hex[:10]
    users = [f"admin-{suffix}@example.test", f"admin2-{suffix}@example.test"]
    async with SessionLocal() as db:
        db.add_all(RegisteredUser(upn=upn, is_admin=True) for upn in users)
        db.add(Meeting(id=meeting_id, drive_item_id=f"synthetic-{suffix}",
                       organizer_upn=users[0], title="[Synthetic] concurrency",
                       state=ProcessingState.approved, transcript="original", extracted_json={},
                       email_delivery_status="not_required", approved_recipients=[]))
        await db.commit()

    async with SessionLocal() as db:
        original_preview = await email_preview(str(meeting_id), db, users[0], [])

    async def save(upn, transcript):
        async with SessionLocal() as db:
            try:
                return await edit_transcript(str(meeting_id), TranscriptEdit(
                    transcript=transcript, expected_revision=None), db, upn)
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code

    results = await asyncio.gather(save(users[0], "first draft"), save(users[1], "second draft"))
    assert await save(f"outsider-{suffix}@example.test", "unauthorized") == 403
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        events = (await db.scalars(select(AuditEvent).where(AuditEvent.meeting_id == meeting_id))).all()
        assert sum(result == 409 for result in results) == 1
        assert sum(isinstance(result, dict) and result.get("ok") for result in results) == 1
        assert meeting.state == ProcessingState.awaiting_review
        assert meeting.extracted_json.get("review_content_revision")
        assert any(event.event_type == "review.reopened" for event in events)
    async with SessionLocal() as db:
        revised_preview = await email_preview(str(meeting_id), db, users[0], [])
        assert original_preview.fingerprint != revised_preview.fingerprint

    item_id = uuid4()
    async with SessionLocal() as db:
        db.add(ActionItem(id=item_id, meeting_id=meeting_id, task="Original task"))
        await db.commit()

    async def current_revision():
        async with SessionLocal() as db:
            return (await db.get(Meeting, meeting_id)).extracted_json["review_content_revision"]

    async def compete(kind, version, user, index):
        async with SessionLocal() as db:
            try:
                if kind == "action":
                    return await edit_item(str(item_id), ActionItemEdit(task=f"Task {index}", expected_revision=version), db, user)
                if kind == "speaker":
                    return await save_speaker_mappings(str(meeting_id), SpeakerMappingIn(mappings={f"Speaker {index}": None}, expected_revision=version), db, user)
                return await save_meeting_decisions(meeting_id, MeetingDecisionsIn(decisions=[{"content": f"Decision {index}", "decision_date": "2026-11-10"}], expected_revision=version), Response(), db, user)
            except HTTPException as exc:
                await db.rollback()
                return exc.status_code

    for kind in ("action", "speaker", "decision"):
        version = await current_revision()
        results = await asyncio.gather(*(compete(kind, version, user, index) for index, user in enumerate(users)))
        assert sum(result == 409 for result in results) == 1, (kind, results)
        assert sum(isinstance(result, (dict, list)) for result in results) == 1, (kind, results)
    async with SessionLocal() as db:
        final_preview = await email_preview(str(meeting_id), db, users[0], [])
        assert "Decision 0" in final_preview.html or "Decision 1" in final_preview.html
    async with SessionLocal() as db:
        result = await approve(str(meeting_id), db, users[0], ApproveMeetingIn(recipients=[], expected_fingerprint=final_preview.fingerprint))
        assert result["state"] == ProcessingState.approved
    async with SessionLocal() as db:
        approved = await db.get(Meeting, meeting_id)
        assert approved.extracted_json["manual_decisions_approved_in_email"] is True
        after_approval = await email_preview(str(meeting_id), db, users[0], [])
        assert after_approval.fingerprint == final_preview.fingerprint
        assert "Decision 0" in after_approval.html or "Decision 1" in after_approval.html
    print("Four concurrent edit paths: one save succeeded and one returned 409; outsider returned 403; review reopened and was audited; old preview no longer matches.")


if __name__ == "__main__":
    asyncio.run(main())
