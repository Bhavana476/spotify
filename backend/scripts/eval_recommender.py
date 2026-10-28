"""Offline evaluation: Precision@5 of the hybrid recommender on a held-out split of the synthetic dataset,
compared against content-only, CF-only and popularity baselines.  Usage: python -m scripts.eval_recommender"""
import json
from collections import Counter

from app.engine import recommender
from app.engine.acoustic import TrackProfile
from app.seed_data import TRACKS
from app.synthetic import generate, split_holdout

K = 5


def tracks() -> list[TrackProfile]:
    return [TrackProfile(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in TRACKS]


def popularity_p_at_k(train, held) -> float:
    pop = Counter(r["track_id"] for r in train if r["liked"] or r["completed"])
    seen = {}
    for r in train:
        seen.setdefault(r["user_id"], set()).add(r["track_id"])
    scores = []
    for uid, rel in held.items():
        ranked = [t for t, _ in pop.most_common() if t not in seen.get(uid, set())][:K]
        scores.append(len(set(ranked) & rel) / K)
    return sum(scores) / len(scores)


def run() -> dict:
    rows = generate()
    train, held = split_holdout(rows)
    held = {u: r for u, r in held.items() if len(r) == 5}
    model = recommender.train(tracks(), train)
    results = {"users": len(held), "interactions_train": len(train), "k": K,
               "hybrid": round(recommender.precision_at_k(model, held, K), 3)}
    for name, (cw, fw) in {"content_only": (1.0, 0.0), "cf_only": (0.0, 1.0)}.items():
        recommender.CONTENT_WEIGHT, recommender.CF_WEIGHT = cw, fw
        results[name] = round(recommender.precision_at_k(model, held, K), 3)
    recommender.CONTENT_WEIGHT, recommender.CF_WEIGHT = 0.4, 0.6
    results["popularity_baseline"] = round(popularity_p_at_k(train, held), 3)
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
