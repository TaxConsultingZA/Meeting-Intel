from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.db import get_db
from app.api.deps import require_registered, require_subscribed
from app.services import cross_user_recordings as service

router = APIRouter(prefix="/recording-processing-requests", tags=["recording requests"])


class EventReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=512)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool


def public_request(request, user_id):
    event = request.event_snapshot
    return {
        "id": str(request.id), "event_id": request.event_id,
        "subject": event.get("subject"), "start": service.utc_iso(event.get("start")),
        "end": service.utc_iso(event.get("end")),
        "organizer_email": service.organizer(event),
        "requester_user_id": str(request.requester_user_id),
        "status": request.status, "created_at": request.created_at,
        "decided_at": request.decided_at,
        "can_decide": request.recording_owner_user_id == user_id and request.status == "pending",
        "meeting_id": str(request.meeting_id) if request.meeting_id else None,
        # Never disclose another user's drive/item IDs or download URLs.
    }


@router.post("")
async def create(body: EventReference, db=Depends(get_db), upn=Depends(require_subscribed)):
    request = await service.create_request(db, upn, body.event_id)
    return public_request(request, request.requester_user_id)


@router.get("")
async def listing(db=Depends(get_db), upn=Depends(require_registered)):
    user = await service.user_by_upn(db, upn)
    requests = await service.list_requests(db, user)
    result = []
    for request in requests:
        out = public_request(request, user.id)
        requester = await db.get(service.RegisteredUser, request.requester_user_id)
        out["requester_name"] = requester.display_name or requester.upn if requester else "Former user"
        result.append(out)
    return result


@router.post("/{request_id}/decision")
async def decide(request_id: UUID, body: Decision, db=Depends(get_db), upn=Depends(require_registered)):
    request = await service.decide_request(db, upn, request_id, body.approved)
    return public_request(request, request.recording_owner_user_id)
