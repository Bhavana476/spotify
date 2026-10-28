"""Synthetic co-listening interaction generator (PRD 6.3: interaction data you generate yourself).

Simulated listeners each have 1-2 favourite clusters. They mostly complete/like tracks from those clusters and
skip a few random others. Seeded RNG -> reproducible dataset and reproducible offline evaluation.
"""
import random

from .seed_data import TRACKS

CLUSTERS: dict[str, list[str]] = {}
for row in TRACKS:
    CLUSTERS.setdefault(row[8], []).append(row[0])
DURATION = {row[0]: row[3] for row in TRACKS}


def generate(n_users: int = 60, seed: int = 7, user_id_offset: int = 1000) -> list[dict]:
    rng = random.Random(seed)
    names = sorted(CLUSTERS)
    rows = []
    for i in range(n_users):
        uid = user_id_offset + i
        favs = rng.sample(names, 3 if rng.random() < 0.3 else 2)
        liked_pool = [t for c in favs for t in CLUSTERS[c]]
        for tid in liked_pool:
            if rng.random() < 0.9:  # listens to most of their favourite clusters
                liked = rng.random() < 0.55
                completed = liked or rng.random() < 0.8
                rows.append({"user_id": uid, "track_id": tid, "liked": liked, "completed": completed,
                             "played_seconds": DURATION[tid] if completed else rng.randint(60, 120)})
        others = [row[0] for row in TRACKS if row[0] not in liked_pool]
        for tid in rng.sample(others, 3):  # random exposure, usually skipped
            completed = rng.random() < 0.2
            rows.append({"user_id": uid, "track_id": tid, "liked": False, "completed": completed,
                         "played_seconds": DURATION[tid] if completed else rng.randint(5, 25)})
    return rows


def split_holdout(rows: list[dict], per_user: int = 5, seed: int = 11):
    """Hold out `per_user` positive interactions per user as the relevance set for Precision@k."""
    rng = random.Random(seed)
    by_user: dict[int, list[dict]] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)
    train, held = [], {}
    for uid, items in by_user.items():
        positives = [r for r in items if r["liked"] or r["completed"]]
        chosen = rng.sample(positives, min(per_user, max(0, len(positives) - 2)))
        held[uid] = {r["track_id"] for r in chosen}
        train.extend(r for r in items if r not in chosen)
    return train, held
