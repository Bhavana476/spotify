"""In-memory track catalog (acoustic profiles + RAG timelines). Reloaded after admin uploads."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .engine.acoustic import TrackProfile
from .models import Track, TrackTimelineEvent

_catalog: dict[str, TrackProfile] = {}


def to_profile(track: Track, timeline: list[TrackTimelineEvent]) -> TrackProfile:
    return TrackProfile(
        id=track.id, title=track.title, artist=track.artist, duration_seconds=track.duration_seconds,
        bpm=track.bpm, camelot_key=track.camelot_key, energy=track.energy, valence=track.valence,
        timeline=[{"id": e.id, "ts": e.ts_seconds, "type": e.event_type, "text": e.payload.get("text", "")}
                  for e in sorted(timeline, key=lambda e: e.ts_seconds)])


async def load(session: AsyncSession):
    tracks = (await session.execute(select(Track))).scalars().all()
    events = (await session.execute(select(TrackTimelineEvent))).scalars().all()
    by_track: dict[str, list] = {}
    for e in events:
        by_track.setdefault(e.track_id, []).append(e)
    _catalog.clear()
    for t in tracks:
        _catalog[t.id] = to_profile(t, by_track.get(t.id, []))


def get(track_id: str) -> TrackProfile | None:
    return _catalog.get(track_id)


def all_tracks() -> list[TrackProfile]:
    return list(_catalog.values())


def profile_json(p: TrackProfile) -> dict:
    return {"trackId": p.id, "title": p.title, "artist": p.artist, "durationSeconds": p.duration_seconds,
            "acoustic": {"bpm": p.bpm, "camelotKey": p.camelot_key, "energy": p.energy, "valence": p.valence},
            "timeline": p.timeline}
