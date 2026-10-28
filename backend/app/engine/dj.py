"""AI DJ service: segue decisions and Soundclash tie-breaks. No socket or DB code — callable from both the
REST API and the WebSocket gateway, and unit-testable in isolation."""
import time
from datetime import datetime, timezone

from . import rag
from .acoustic import TrackProfile, camelot_relation, bpm_relation, rank_segues


async def decide_segue(current: TrackProfile, queued: list[TrackProfile], catalog: list[TrackProfile],
                       sentiment: float, recent_ids: list[str], tolerance_pct: float = 8.0,
                       verbosity: str = "normal", locked: TrackProfile | None = None,
                       exclude_ids: set[str] | None = None) -> dict | None:
    """Picks the next track. Every decision with aiSelected=True satisfies the BPM + Camelot hard rules.

    - locked: a human decision (host promote / Soundclash winner) already holds Next Up. It is honoured; if it
      breaks the rules the decision is flagged aiSelected=False ("crowd's call"), never silently relabelled.
    - otherwise rank the rule-valid queued tracks; if none, dig through the catalog for one.
    """
    started = time.perf_counter()
    exclude = set(exclude_ids or ())
    from_catalog = False
    if locked is not None:
        ranked = rank_segues(current, [locked], sentiment, recent_ids, tolerance_pct)
        if not ranked:
            bpm = bpm_relation(current.bpm, locked.bpm, tolerance_pct)
            return {
                "selectedTrackId": locked.id, "aiSelected": False, "fromCatalog": False,
                "matchReason": {"bpmDeltaPct": round(abs(locked.bpm - current.bpm) / current.bpm * 100, 2),
                                "bpmCompatible": bpm is not None,
                                "camelotRelation": camelot_relation(current.camelot_key, locked.camelot_key)
                                or "clash"},
                "transitionScript": f"The crowd has spoken — hard cut into \"{locked.title}\" by {locked.artist}. "
                                    f"Not a textbook mix, but it's your call!",
                "sourceEvents": [], "generator": "template",
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "latencyMs": round((time.perf_counter() - started) * 1000, 1)}
        choice = ranked[0]
    else:
        pool = [t for t in queued if t.id not in exclude]
        ranked = rank_segues(current, pool, sentiment, recent_ids, tolerance_pct)
        if not ranked:
            queued_ids = {t.id for t in queued}
            crate = [t for t in catalog if t.id not in exclude and t.id not in queued_ids
                     and t.id not in set(recent_ids)]
            ranked = rank_segues(current, crate, sentiment, recent_ids, tolerance_pct)
            from_catalog = True
        if not ranked:
            return None
        choice = ranked[0]
    script = await rag.generate_transition(current, choice, sentiment, verbosity)
    return {"selectedTrackId": choice.track.id, "aiSelected": True, "fromCatalog": from_catalog,
            "matchReason": choice.match_reason(), "transitionScript": script["transitionScript"],
            "sourceEvents": script["sourceEvents"], "generator": script["generator"],
            "alternatives": [c.track.id for c in ranked[1:4]],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "latencyMs": round((time.perf_counter() - started) * 1000, 1)}


def break_tie(current: TrackProfile | None, tied: list[TrackProfile], sentiment: float,
              tolerance_pct: float = 8.0) -> str:
    """Deterministic AI tie-break: best-ranked rule-valid segue, else lowest track id."""
    if current is not None:
        ranked = rank_segues(current, tied, sentiment, [], tolerance_pct)
        if ranked:
            return ranked[0].track.id
    return sorted(t.id for t in tied)[0]
