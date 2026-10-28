import asyncio
import itertools
import random

import pytest

from app.engine import dj
from app.engine.acoustic import (CAMELOT_KEYS, TrackProfile, bpm_relation, camelot_relation, is_valid_segue,
                                 match_segue, parse_camelot, rank_segues)
from app.seed_data import TRACKS


def T(tid, bpm, key, energy=0.5):
    return TrackProfile(tid, tid, "Artist", 200, bpm, key, energy, 0.5, [{"id": f"e_{tid}", "ts": 1,
                                                                          "type": "trivia", "text": "fact"}])


CATALOG = [TrackProfile(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                        [{"id": f"evt_{r[0]}_{i}", "ts": ts, "type": ty, "text": tx}
                         for i, (ts, ty, tx) in enumerate(r[9])]) for r in TRACKS]


def independent_rule_check(cur: TrackProfile, cand: TrackProfile, tol=8.0) -> bool:
    """Re-implementation of PRD 6.2 written separately from the engine, used as the oracle."""
    bpm_ok = any(abs(cand.bpm - cur.bpm * m) <= cur.bpm * m * tol / 100 for m in (1, 0.5, 2))
    n1, l1 = int(cur.camelot_key[:-1]), cur.camelot_key[-1]
    n2, l2 = int(cand.camelot_key[:-1]), cand.camelot_key[-1]
    key_ok = (n1 == n2) or (l1 == l2 and ((n1 % 12) + 1 == n2 or (n2 % 12) + 1 == n1))
    return bpm_ok and key_ok


def test_24_valid_keys_and_parsing():
    assert len(CAMELOT_KEYS) == 24
    assert parse_camelot("8a") == (8, "A")
    for bad in ("13A", "0B", "8C", "", "A8", "8", None):
        with pytest.raises(ValueError):
            parse_camelot(bad)


@pytest.mark.parametrize("a,b,expected", [
    ("8A", "8A", "identical"), ("8A", "7A", "adjacent"), ("8A", "9A", "adjacent"), ("8A", "8B", "relative"),
    ("12A", "1A", "adjacent"), ("1B", "12B", "adjacent"), ("8A", "9B", None), ("8A", "10A", None),
    ("8A", "3A", None), ("5B", "5A", "relative"), ("8B", "7A", None)])
def test_camelot_relations(a, b, expected):
    assert camelot_relation(a, b) == expected


@pytest.mark.parametrize("cur,cand,ok", [
    (120, 110.4, True), (120, 129.6, True), (120, 110.3, False), (120, 129.7, False),
    (120, 60, True), (120, 240, True), (120, 64.8, True), (120, 65, False), (86, 172, True), (172, 86, True),
    (120, 90, False)])
def test_bpm_tolerance_window(cur, cand, ok):
    assert (bpm_relation(cur, cand, 8) is not None) is ok


def test_bpm_relation_names():
    assert bpm_relation(86, 172)[0] == "double_time"
    assert bpm_relation(172, 86)[0] == "half_time"
    assert bpm_relation(124, 126)[0] == "same"


def test_invalid_candidates_never_selected():
    cur = T("cur", 124, "8A")
    pool = [T("clash_key", 124, "3B"), T("clash_bpm", 140, "8A"), T("ok", 126, "9A")]
    assert [c.track.id for c in rank_segues(cur, pool)] == ["ok"]
    assert match_segue(cur, pool[:2]) is None


def test_ranking_weights_prefer_harmonic_closeness():
    cur = T("cur", 124, "8A", 0.7)
    best = match_segue(cur, [T("adj", 124, "9A", 0.7), T("same", 124, "8A", 0.7)])
    assert best.track.id == "same" and best.camelot_relation == "identical"


def test_sentiment_steers_energy():
    cur = T("cur", 124, "8A", 0.6)
    low, high = T("low", 124, "8A", 0.3), T("high", 124, "8A", 0.9)
    assert match_segue(cur, [low, high], sentiment=0.95).track.id == "high"
    assert match_segue(cur, [low, high], sentiment=0.05).track.id == "low"


def test_recency_deprioritises_recent_tracks():
    cur = T("cur", 124, "8A", 0.6)
    a, b = T("a", 124, "8A", 0.6), T("b", 124, "8A", 0.6)
    assert match_segue(cur, [a, b], recent_ids=["a"]).track.id == "b"


def test_100_percent_rule_compliance_over_simulated_segues():
    """PRD 6.2 acceptance: >= 20 simulated decisions, every selected segue rule-valid (we run 500)."""
    rng = random.Random(42)
    decisions = 0
    for _ in range(500):
        current = rng.choice(CATALOG)
        candidates = rng.sample(CATALOG, rng.randint(1, 10))
        choice = match_segue(current, candidates, sentiment=rng.random(),
                             recent_ids=[t.id for t in rng.sample(CATALOG, 3)])
        if choice is None:
            assert not any(independent_rule_check(current, c) for c in candidates if c.id != current.id)
            continue
        decisions += 1
        assert independent_rule_check(current, choice.track)
        assert is_valid_segue(current, choice.track)
    assert decisions >= 20
    print(f"\nrule-compliant segue decisions: {decisions}/{decisions}")


def test_engine_matches_oracle_on_every_catalog_pair():
    for a, b in itertools.permutations(CATALOG, 2):
        assert is_valid_segue(a, b) == independent_rule_check(a, b), (a.id, b.id)


def test_full_segue_chain_exists_in_seed_catalog():
    chain = ["t_5001", "t_6001", "t_6002", "t_5002"]  # lo-fi -> double-time DnB -> adjacent key -> half-time
    by_id = {t.id: t for t in CATALOG}
    for a, b in zip(chain, chain[1:]):
        assert is_valid_segue(by_id[a], by_id[b]), (a, b)


def test_ai_dj_decision_always_valid_and_explained():
    async def go():
        rng = random.Random(3)
        for _ in range(30):
            cur = rng.choice(CATALOG)
            d = await dj.decide_segue(cur, rng.sample(CATALOG, 6), CATALOG, rng.random(), [])
            assert d is not None  # catalog fallback guarantees a valid option exists for every seed track
            chosen = next(t for t in CATALOG if t.id == d["selectedTrackId"])
            assert d["aiSelected"] and independent_rule_check(cur, chosen)
            assert {"bpmDeltaPct", "camelotRelation", "energyFit"} <= d["matchReason"].keys()
            assert d["transitionScript"] and d["latencyMs"] < 3000
            assert set(d["sourceEvents"]) <= {e["id"] for e in chosen.timeline}
    asyncio.run(go())


def test_locked_human_choice_is_never_labelled_ai_selected_when_invalid():
    async def go():
        cur, clash = T("cur", 124, "8A"), T("clash", 90, "3B")
        d = await dj.decide_segue(cur, [clash], [], 0.5, [], locked=clash)
        assert d["selectedTrackId"] == "clash" and d["aiSelected"] is False
    asyncio.run(go())
