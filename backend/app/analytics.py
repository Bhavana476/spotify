"""Session analytics derived purely from the append-only queue_events log, so the numbers always reconcile."""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import QueueEvent, SoundclashBattle, SoundclashCandidate


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def compute(events: list[QueueEvent]) -> dict:
    events = sorted(events, key=lambda e: e.ts)
    started = next((e.ts for e in events if e.type == "loungeStarted"), None)
    ended = next((e.ts for e in events if e.type == "loungeEnded"), None)
    origin = started or (events[0].ts if events else time.time())
    counts: dict[str, int] = {}
    for e in events:
        counts[e.type] = counts.get(e.type, 0) + 1
    segues = [e.payload for e in events if e.type == "segue"]
    return {
        "durationSeconds": round(((ended or time.time()) - started), 1) if started else 0,
        "startedAt": started, "endedAt": ended,
        "peakConcurrentParticipants": max((e.payload.get("participantCount", 0) for e in events
                                           if e.type == "presence"), default=0),
        "soundclashBattles": counts.get("battleResolved", 0),
        "aiQuestionsAsked": counts.get("aiQuestion", 0),
        "chatMessages": counts.get("chat", 0),
        "votes": counts.get("vote", 0),
        "tracksPlayed": counts.get("trackPlayed", 0),
        "aiSegues": sum(1 for s in segues if s.get("aiSelected")),
        "humanOverrideSegues": sum(1 for s in segues if not s.get("aiSelected")),
        "aiSegueLatencyP95Ms": _p95([s["latencyMs"] for s in segues if "latencyMs" in s]),
        "sentimentTimeline": [{"t": round(e.ts - origin, 1), "score": e.payload["rollingScore"],
                               "samples": e.payload.get("sampleSize", 0)}
                              for e in events if e.type == "sentimentTick"],
        "eventCount": len(events),
    }


async def battles(session: AsyncSession, lounge_id: str) -> list[dict]:
    rows = (await session.execute(select(SoundclashBattle).where(SoundclashBattle.lounge_id == lounge_id)
                                  .order_by(SoundclashBattle.opened_at))).scalars().all()
    if not rows:
        return []
    cands = (await session.execute(select(SoundclashCandidate).where(
        SoundclashCandidate.battle_id.in_([b.id for b in rows])))).scalars().all()
    by_battle: dict[str, list] = {}
    for c in cands:
        by_battle.setdefault(c.battle_id, []).append({"trackId": c.track_id, "votes": c.vote_count,
                                                      "submittedBy": c.submitted_by_user_id})
    return [{"battleId": b.id, "openedAt": b.opened_at.isoformat(), "winningTrackId": b.winning_track_id,
             "candidates": sorted(by_battle.get(b.id, []), key=lambda c: -c["votes"])} for b in rows]


async def session_analytics(session: AsyncSession, lounge_id: str) -> dict:
    events = (await session.execute(select(QueueEvent).where(QueueEvent.lounge_id == lounge_id))).scalars().all()
    return {**compute(list(events)), "battles": await battles(session, lounge_id)}
