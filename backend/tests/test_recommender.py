from app.engine import recommender
from app.engine.acoustic import TrackProfile


def _tracks():
    return [TrackProfile(f"t{i}", f"T{i}", "A", 200, 120 + i, "8A", 0.5, 0.5) for i in range(4)]


def test_cold_start_ranks_by_popularity_not_flat_scores():
    rows = [{"user_id": u, "track_id": "t2", "completed": True} for u in range(5)] + \
           [{"user_id": 9, "track_id": "t1", "liked": True}]
    model = recommender.train(_tracks(), rows)
    recs = recommender.recommend(model, user_id=42, k=4)
    assert recs[0]["trackId"] == "t2" and recs[0]["popular"]
    assert len({r["score"] for r in recs}) > 1


def test_personalised_user_is_not_given_popularity_fallback():
    rows = [{"user_id": 1, "track_id": "t0", "liked": True}, {"user_id": 2, "track_id": "t0", "liked": True},
            {"user_id": 2, "track_id": "t3", "liked": True}]
    recs = recommender.recommend(recommender.train(_tracks(), rows), user_id=1, k=3)
    assert not recs[0].get("popular") and recs[0]["trackId"] == "t3"
