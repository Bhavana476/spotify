import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import catalog
from ..analytics import session_analytics
from ..db import get_session
from ..engine import dj, rag
from ..events import sink
from ..gateway.hub import Runtime, hub
from ..gateway.lounge_state import ROLE_RANK, QueueError
from ..models import ChatMessage, Lounge, QueueEvent, User
from ..schemas import LoungeCreateIn, SegueIn
from ..security import current_user, sanitize_text

router = APIRouter(prefix="/api/v1/lounges", tags=["lounges"])
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def lounge_json(lg: Lounge) -> dict:
    return {"loungeId": lg.id, "inviteCode": lg.invite_code, "status": lg.status, "hostUserId": lg.host_user_id,
            "vibeProfile": lg.vibe_profile, "seedTrackId": lg.seed_track_id, "maxParticipants": lg.max_participants,
            "bpmTolerancePct": lg.bpm_tolerance_pct, "soundclashEnabled": lg.soundclash_enabled,
            "aiVerbosity": lg.ai_verbosity, "createdAt": lg.created_at.isoformat().replace("+00:00", "Z"),
            "endedAt": lg.ended_at.isoformat() if lg.ended_at else None}


async def _runtime(lounge_id: str) -> Runtime:
    rt = await hub.get(lounge_id)
    if rt is None:
        raise HTTPException(404, "Lounge not found")
    return rt


def _require(rt: Runtime, user: User, minimum: str):
    if ROLE_RANK[rt.state.role_of(user.id, user.role)] < ROLE_RANK[minimum]:
        raise HTTPException(403, f"Requires lounge role '{minimum}' or higher")


@router.post("", status_code=201)
async def create_lounge(body: LoungeCreateIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    if catalog.get(body.seedTrackId) is None:
        raise HTTPException(422, "seedTrackId does not exist")
    code = "SP-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    while (await session.execute(select(Lounge).where(Lounge.invite_code == code))).scalar_one_or_none():
        code = "SP-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    lounge = Lounge(id=f"lg_{uuid.uuid4().hex[:8]}", invite_code=code, host_user_id=user.id,
                    vibe_profile=sanitize_text(body.vibeProfile, 64), seed_track_id=body.seedTrackId,
                    max_participants=body.maxParticipants, bpm_tolerance_pct=body.bpmTolerancePct,
                    soundclash_enabled=body.soundclashEnabled, ai_verbosity=body.aiVerbosity)
    session.add(lounge)
    if user.role == "listener":
        user.role = "host"  # account badge; lounge-level authority is always resolved per lounge
    await session.commit()
    return {"loungeId": lounge.id, "inviteCode": code, "status": lounge.status, "hostUserId": user.id,
            "createdAt": lounge.created_at.isoformat().replace("+00:00", "Z")}


@router.get("")
async def list_lounges(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Lounge).where(Lounge.status != "ended")
                                  .order_by(Lounge.created_at.desc()).limit(50))).scalars().all()
    out = []
    for lg in rows:
        rt = hub.runtimes.get(lg.id)
        out.append({**lounge_json(lg), "participantCount": len(rt.state.connected_ids()) if rt else 0})
    return out


@router.get("/by-code/{code}")
async def by_code(code: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    lg = (await session.execute(select(Lounge).where(Lounge.invite_code == code.strip().upper()))).scalar_one_or_none()
    if lg is None:
        raise HTTPException(404, "No lounge with that invite code")
    return lounge_json(lg)


@router.get("/{lounge_id}")
async def get_lounge(lounge_id: str, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    lg = await session.get(Lounge, lounge_id)
    if lg is None:
        raise HTTPException(404, "Lounge not found")
    rt = hub.runtimes.get(lounge_id)
    return {**lounge_json(lg), "state": rt.state.snapshot(rt.account_roles) if rt else None,
            "summary": lg.summary}


@router.post("/{lounge_id}/start")
async def start_lounge(lounge_id: str, user: User = Depends(current_user)):
    rt = await _runtime(lounge_id)
    _require(rt, user, "host")
    if rt.state.status == "ended":
        raise HTTPException(409, "Lounge has ended")
    await rt.start()
    return {"status": rt.state.status}


@router.post("/{lounge_id}/end")
async def end_lounge(lounge_id: str, user: User = Depends(current_user)):
    rt = await _runtime(lounge_id)
    _require(rt, user, "host")
    if rt.state.status == "ended":
        raise HTTPException(409, "Lounge already ended")
    await rt.end()
    return {"status": "ended"}


@router.post("/{lounge_id}/queue/{entry_id}/promote")
async def promote(lounge_id: str, entry_id: str, user: User = Depends(current_user)):
    rt = await _runtime(lounge_id)
    _require(rt, user, "co_dj")
    try:
        item = rt.state.promote(entry_id, "host")
    except QueueError as err:
        raise HTTPException(409 if err.code == "frozen" else 404, err.message)
    rt.state.pending_segue = None
    sink.event(lounge_id, "override", {"entryId": entry_id, "trackId": item.track_id}, user.id)
    await rt.push_state("override")
    return {"queue": rt.state.queue_view()}


@router.post("/{lounge_id}/ai/segue")
async def ai_segue(lounge_id: str, body: SegueIn, user: User = Depends(current_user)):
    """Stateless segue decision over explicit candidates (PRD 7.3.3). With apply=true and a live lounge, the
    gateway's own decision flow runs instead so the result is broadcast to the room."""
    rt = await _runtime(lounge_id)
    _require(rt, user, "co_dj")
    current = catalog.get(body.currentTrackId)
    candidates = [catalog.get(t) for t in body.candidateTrackIds]
    if current is None or any(c is None for c in candidates):
        raise HTTPException(422, "Unknown track id in request")
    if body.apply and rt.state.status == "live":
        rt.state.pending_segue = None
        decision = await rt.run_segue("api")
        if decision is None:
            raise HTTPException(409, "No valid segue available right now")
        return decision
    decision = await dj.decide_segue(current, candidates, [], body.currentSentimentScore, rt.state.history[-5:],
                                     rt.state.settings["bpmTolerancePct"], rt.state.settings["aiVerbosity"])
    if decision is None:
        raise HTTPException(409, "No candidate satisfies the BPM and Camelot-key rules")
    decision.pop("fromCatalog", None)
    sink.event(lounge_id, "segueQuery", {"fromTrackId": current.id, **decision}, user.id)
    return decision


@router.post("/{lounge_id}/ai/ask")
async def ai_ask(lounge_id: str, body: dict, user: User = Depends(current_user)):
    rt = await _runtime(lounge_id)
    question = sanitize_text(str(body.get("question", "")), 300)
    track_id = body.get("trackId") or (rt.state.now_playing or {}).get("trackId") or rt.seed_track_id
    track = catalog.get(track_id)
    if not question or track is None:
        raise HTTPException(422, "question and a valid trackId are required")
    started = time.perf_counter()
    result = await rag.answer_question(question, track)
    result["latencyMs"] = round((time.perf_counter() - started) * 1000, 1)
    result["sources"] = [e for e in track.timeline if e["id"] in result["sourceEvents"]]
    sink.event(lounge_id, "aiQuestion", {"question": question, **result}, user.id)
    return result


@router.get("/{lounge_id}/chat")
async def chat_history(lounge_id: str, limit: int = 100, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(ChatMessage).where(ChatMessage.lounge_id == lounge_id)
                                  .order_by(ChatMessage.ts_seconds.desc()).limit(min(limit, 500)))).scalars().all()
    return [{"messageId": m.id, "userId": m.user_id, "msgType": m.msg_type, "body": m.body,
             "sentimentScore": m.sentiment_score, "tsSeconds": m.ts_seconds} for m in reversed(rows)]


@router.get("/{lounge_id}/analytics")
async def analytics(lounge_id: str, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    lg = await session.get(Lounge, lounge_id)
    if lg is None:
        raise HTTPException(404, "Lounge not found")
    participated = (await session.execute(select(QueueEvent.id).where(
        QueueEvent.lounge_id == lounge_id, QueueEvent.user_id == user.id).limit(1))).first()
    if user.role != "admin" and user.id != lg.host_user_id and not participated:
        raise HTTPException(403, "Only participants, the host or an admin can view these analytics")
    await sink.flush()
    return {"lounge": lounge_json(lg), **await session_analytics(session, lounge_id)}
