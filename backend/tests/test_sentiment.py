import json
from pathlib import Path

from app.engine.sentiment import RollingSentiment, bucket, classify, score_message

DATA = json.loads((Path(__file__).parent / "data" / "sentiment_test.json").read_text(encoding="utf-8"))


def test_accuracy_on_labeled_test_set():
    correct = sum(1 for text, label in DATA if classify(text)[0] == label)
    accuracy = correct / len(DATA)
    print(f"\nsentiment accuracy: {correct}/{len(DATA)} = {accuracy:.3f}")
    assert len(DATA) >= 75
    assert accuracy >= 0.85


def test_negation_flips_polarity():
    assert score_message("this is good") > 0
    assert score_message("this is not good") < 0


def test_intensifier_and_emoji():
    assert score_message("so good") > score_message("good")
    assert bucket(score_message("🔥🔥")) == "positive"
    assert bucket(score_message("😴")) == "negative"


def test_score_bounded():
    assert -1 <= score_message("terrible awful trash garbage worst " * 10) <= 1
    assert -1 <= score_message("amazing banger fire love " * 10) <= 1


def test_rolling_score_shifts_within_one_window():
    now = [1000.0]
    agg = RollingSentiment(window_seconds=30, clock=lambda: now[0])
    for i in range(10):
        agg.add(score_message("this is a banger 🔥"), ts=now[0])
        now[0] += 1
    hyped = agg.score()
    assert hyped > 0.65
    for i in range(10):  # deliberate burst of negative chat
        agg.add(score_message("so boring, skip this 😴"), ts=now[0])
        now[0] += 1
    assert agg.score() < hyped - 0.2
    now[0] += 31  # one full window later the old burst has aged out
    for _ in range(3):
        agg.add(score_message("energy is dead"), ts=now[0])
    assert agg.score() < 0.35
    assert agg.snapshot()["sampleSize"] == 3


def test_empty_window_is_neutral():
    assert RollingSentiment(10).score() == 0.5
