from fastapi import APIRouter, Depends, HTTPException, Query

from .. import catalog
from ..engine.acoustic import rank_segues
from ..security import current_user

router = APIRouter(prefix="/api/v1/tracks", tags=["tracks"], dependencies=[Depends(current_user)])


@router.get("")
async def list_tracks(q: str | None = Query(None, max_length=100)):
    tracks = catalog.all_tracks()
    if q:
        needle = q.lower()
        tracks = [t for t in tracks if needle in t.title.lower() or needle in t.artist.lower()]
    return [{k: v for k, v in catalog.profile_json(t).items() if k != "timeline"}
            for t in sorted(tracks, key=lambda t: t.title)]


@router.get("/{track_id}/acoustic-profile")
async def acoustic_profile(track_id: str):
    track = catalog.get(track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    return catalog.profile_json(track)


@router.get("/{track_id}/compatible")
async def compatible(track_id: str, sentiment: float = Query(0.5, ge=0, le=1),
                     tolerance: float = Query(8, gt=0, le=8)):
    """Every rule-valid segue from this track, ranked — used by the Soundclash picker to flag safe choices."""
    track = catalog.get(track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    ranked = rank_segues(track, catalog.all_tracks(), sentiment, [], tolerance)
    return [{"trackId": c.track.id, "title": c.track.title, "artist": c.track.artist, **c.match_reason()}
            for c in ranked]
