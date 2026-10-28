from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import catalog, recs
from ..db import get_session
from ..engine import recommender
from ..gateway.hub import hub
from ..models import Lounge, QueueEvent, User
from ..security import current_user
from .lounges import lounge_json

router = APIRouter(prefix="/api/v1/me", tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    attended = select(QueueEvent.lounge_id).where(QueueEvent.user_id == user.id, QueueEvent.type == "presence")
    rows = (await session.execute(select(Lounge).where(or_(Lounge.host_user_id == user.id,
                                                           Lounge.id.in_(attended)))
                                  .order_by(Lounge.created_at.desc()).limit(30))).scalars().all()
    history = [{**lounge_json(lg), "hosted": lg.host_user_id == user.id,
                "summary": {k: v for k, v in (lg.summary or {}).items() if k != "sentimentTimeline"}}
               for lg in rows]
    active = [{"loungeId": rt.lounge_id, "vibeProfile": rt.state.settings["vibeProfile"],
               "inviteCode": rt.state.settings["inviteCode"], "participantCount": len(rt.state.connected_ids()),
               "nowPlaying": rt.state.now_playing and rt.state.now_playing["trackId"]} for rt in hub.live()]
    model = recs.model()
    return {"user": {"userId": user.id, "displayName": user.display_name, "role": user.role},
            "lounges": history, "activeLounges": active,
            "tasteProfile": recommender.taste_profile(model, user.id) if model else None,
            "recommendations": _rail(model, user.id, 10)}


def _rail(model, user_id: int, k: int) -> list[dict]:
    if model is None:
        return []
    out = []
    for r in recommender.recommend(model, user_id, k):
        t = catalog.get(r["trackId"])
        if t:
            out.append({**r, "title": t.title, "artist": t.artist, "bpm": t.bpm, "camelotKey": t.camelot_key,
                        "energy": t.energy})
    return out


@router.get("/recommendations")
async def recommendations(k: int = 10, user: User = Depends(current_user)):
    return {"items": _rail(recs.model(), user.id, min(max(k, 1), 50)), "model": recs.status()}
