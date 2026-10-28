"""Hybrid recommender: content-based (acoustic similarity) + item-item collaborative filtering.

"Training" builds an item co-occurrence matrix and per-track feature vectors; it is cheap enough to rebuild
in a background batch job whenever new interactions are flushed, so the rail updates without a redeploy.
"""
import math
from collections import defaultdict
from dataclasses import dataclass

from .acoustic import TrackProfile, parse_camelot

CONTENT_WEIGHT, CF_WEIGHT = 0.4, 0.6


def interaction_weight(completed: bool, liked: bool, played_seconds: float) -> float:
    """Implicit feedback strength. Skips (short, not completed, not liked) count as negative."""
    if liked:
        return 2.0
    if completed:
        return 1.0
    return -0.5 if played_seconds < 30 else 0.25


def feature_vector(t: TrackProfile) -> list[float]:
    number, letter = parse_camelot(t.camelot_key)
    angle = 2 * math.pi * (number - 1) / 12
    return [min(t.bpm, 200) / 200, t.energy, t.valence, 0.5 * math.cos(angle), 0.5 * math.sin(angle),
            0.3 if letter == "B" else -0.3]


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Model:
    tracks: dict[str, TrackProfile]
    vectors: dict[str, list[float]]
    user_weights: dict[int, dict[str, float]]
    co_occurrence: dict[str, dict[str, float]]
    item_norm: dict[str, float]


def train(tracks: list[TrackProfile], interactions: list[dict]) -> Model:
    user_weights: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for it in interactions:
        user_weights[it["user_id"]][it["track_id"]] += interaction_weight(
            it.get("completed", False), it.get("liked", False), it.get("played_seconds", 0))
    co = defaultdict(lambda: defaultdict(float))
    norm = defaultdict(float)
    for weights in user_weights.values():
        positives = [t for t, w in weights.items() if w > 0]
        for a in positives:
            norm[a] += 1
            for b in positives:
                if a != b:
                    co[a][b] += 1
    return Model(tracks={t.id: t for t in tracks}, vectors={t.id: feature_vector(t) for t in tracks},
                 user_weights={u: dict(w) for u, w in user_weights.items()},
                 co_occurrence={a: dict(b) for a, b in co.items()}, item_norm=dict(norm))


def taste_profile(model: Model, user_id: int) -> dict | None:
    weights = {t: w for t, w in model.user_weights.get(user_id, {}).items() if w > 0 and t in model.tracks}
    if not weights:
        return None
    total = sum(weights.values())
    bpms = [model.tracks[t].bpm for t in weights]
    keys = defaultdict(float)
    for t, w in weights.items():
        keys[model.tracks[t].camelot_key] += w
    return {"bpmRange": [min(bpms), max(bpms)],
            "avgBpm": round(sum(model.tracks[t].bpm * w for t, w in weights.items()) / total, 1),
            "avgEnergy": round(sum(model.tracks[t].energy * w for t, w in weights.items()) / total, 3),
            "avgValence": round(sum(model.tracks[t].valence * w for t, w in weights.items()) / total, 3),
            "preferredKeys": [k for k, _ in sorted(keys.items(), key=lambda kv: -kv[1])[:3]],
            "tracksConsidered": len(weights)}


def recommend(model: Model, user_id: int, k: int = 10, exclude_seen: bool = True) -> list[dict]:
    seen = model.user_weights.get(user_id, {})
    positives = {t: w for t, w in seen.items() if w > 0 and t in model.vectors}
    if not positives:
        return _popular(model, seen if exclude_seen else {}, k)
    if positives:
        dims = len(next(iter(model.vectors.values())))
        total = sum(positives.values())
        profile = [sum(model.vectors[t][i] * w for t, w in positives.items()) / total for i in range(dims)]
    else:
        profile = None
    results = []
    for tid, vec in model.vectors.items():
        if exclude_seen and tid in seen:
            continue
        content = (_cosine(profile, vec) + 1) / 2 if profile else 0.5
        cf = 0.0
        if positives:
            for src, w in positives.items():
                co = model.co_occurrence.get(src, {}).get(tid, 0.0)
                if co:
                    cf += w * co / math.sqrt(model.item_norm.get(src, 1) * model.item_norm.get(tid, 1))
            cf /= sum(positives.values())
        results.append((tid, content, cf))
    max_cf = max((r[2] for r in results), default=0) or 1.0
    scored = [{"trackId": tid, "score": round(CONTENT_WEIGHT * c + CF_WEIGHT * (cf / max_cf), 4),
               "contentScore": round(c, 4), "cfScore": round(cf / max_cf, 4)} for tid, c, cf in results]
    scored.sort(key=lambda r: (-r["score"], r["trackId"]))
    return scored[:k]


def _popular(model: Model, seen: dict, k: int) -> list[dict]:
    """Cold start: with no positive history there is nothing to personalise on, so rank by how many listeners
    completed or liked each track instead of giving every track the same flat score."""
    top = max(model.item_norm.values(), default=0) or 1.0
    scored = [{"trackId": tid, "score": round(model.item_norm.get(tid, 0) / top, 4), "contentScore": 0.0,
               "cfScore": 0.0, "popular": True} for tid in model.vectors if tid not in seen]
    scored.sort(key=lambda r: (-r["score"], r["trackId"]))
    return scored[:k]


def precision_at_k(model: Model, held_out: dict[int, set[str]], k: int = 5) -> float:
    precisions = []
    for user_id, relevant in held_out.items():
        if not relevant:
            continue
        recs = [r["trackId"] for r in recommend(model, user_id, k)]
        precisions.append(len(set(recs) & relevant) / k)
    return sum(precisions) / len(precisions) if precisions else 0.0
