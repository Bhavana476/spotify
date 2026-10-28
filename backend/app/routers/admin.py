"""Admin-only: acoustic-feature management (PRD 6.3) and account roles."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import catalog, recs
from ..db import get_session
from ..models import ROLES, Track, TrackTimelineEvent, User
from ..schemas import TrackUploadIn
from ..security import require_role, sanitize_text

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_role("admin"))])


@router.put("/tracks", status_code=201)
async def upsert_track(body: TrackUploadIn, session: AsyncSession = Depends(get_session)):
    """Create or replace a track's acoustic profile and RAG timeline. Validation errors return 422 with the
    offending field, e.g. camelotKey '13C' -> "'13C' is not a valid Camelot key (expected 1A-12B)"."""
    track_id = body.trackId or f"t_{uuid.uuid4().hex[:8]}"
    track = await session.get(Track, track_id)
    if track is None:
        track = Track(id=track_id)
        session.add(track)
    track.title, track.artist = sanitize_text(body.title, 200), sanitize_text(body.artist, 200)
    track.duration_seconds, track.audio_asset_url = body.durationSeconds, body.audioAssetUrl
    track.bpm, track.camelot_key = body.acoustic.bpm, body.acoustic.camelotKey
    track.energy, track.valence = body.acoustic.energy, body.acoustic.valence
    await session.execute(delete(TrackTimelineEvent).where(TrackTimelineEvent.track_id == track_id))
    for entry in body.timeline:
        session.add(TrackTimelineEvent(id=f"evt_{uuid.uuid4().hex[:8]}", track_id=track_id, ts_seconds=entry.ts,
                                       event_type=entry.type, payload={"text": sanitize_text(entry.text, 400)}))
    await session.commit()
    await catalog.load(session)
    await recs.retrain(force=True)
    return catalog.profile_json(catalog.get(track_id))


@router.post("/tracks/validate")
async def validate_only(body: TrackUploadIn):
    """Dry-run validation for the upload form."""
    return {"valid": True, "normalized": body.model_dump()}


@router.delete("/tracks/{track_id}", status_code=204)
async def delete_track(track_id: str, session: AsyncSession = Depends(get_session)):
    track = await session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    await session.execute(delete(TrackTimelineEvent).where(TrackTimelineEvent.track_id == track_id))
    await session.delete(track)
    await session.commit()
    await catalog.load(session)


@router.get("/users")
async def users(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return [{"userId": u.id, "email": u.email, "displayName": u.display_name, "role": u.role} for u in rows]


@router.patch("/users/{user_id}/role")
async def set_role(user_id: int, body: dict, session: AsyncSession = Depends(get_session)):
    role = body.get("role")
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    user.role = role
    await session.commit()
    return {"userId": user.id, "role": user.role}


@router.post("/recommender/retrain")
async def retrain():
    return await recs.retrain(force=True)
