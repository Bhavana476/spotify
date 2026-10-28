import asyncio

from app.engine import rag
from app.engine.acoustic import TrackProfile, match_segue

TRACK = TrackProfile("t_1", "Night Drive", "Nova Circuit", 200, 124, "8A", 0.8, 0.6, [
    {"id": "evt_a", "ts": 12, "type": "sample_credit", "text": "The vocal chop is sampled from a 1981 soul record."},
    {"id": "evt_b", "ts": 40, "type": "artist_bio", "text": "Nova Circuit is a duo from Rotterdam."},
    {"id": "evt_c", "ts": 90, "type": "trivia", "text": "Produced during an all-night session in Berlin."},
])


def ask(q):
    return asyncio.run(rag.answer_question(q, TRACK))


def test_sample_question_cites_sample_credit():
    r = ask("where's this sample from?")
    assert r["grounded"] and r["sourceEvents"][0] == "evt_a"
    assert "1981 soul record" in r["answer"]


def test_artist_question_cites_bio():
    r = ask("who is the artist behind this?")
    assert "evt_b" in r["sourceEvents"]


def test_declines_when_no_metadata_matches():
    r = ask("what was the chart position in Japan?")
    assert r["grounded"] is False and r["sourceEvents"] == []
    assert "rather not guess" in r["answer"]


def test_answer_contains_only_retrieved_text():
    r = ask("tell me about the session where it was produced")
    cited_text = " ".join(e["text"] for e in TRACK.timeline if e["id"] in r["sourceEvents"])
    body = r["answer"].split(": ", 1)[1]
    for sentence in body.replace("Also — ", "").split(". "):
        assert sentence.strip(". ") in cited_text


def test_citation_verifier_rejects_fabricated_ids():
    assert rag._verify_citations("Cool fact [evt_a]", TRACK.timeline) == ["evt_a"]
    assert rag._verify_citations("Made up [evt_zzz]", TRACK.timeline) is None
    assert rag._verify_citations("No citation at all", TRACK.timeline) is None


def test_transition_script_grounded_in_next_track():
    nxt = TrackProfile("t_2", "Pulse", "Kairo", 200, 125, "9A", 0.85, 0.7,
                       [{"id": "evt_k", "ts": 5, "type": "artist_bio", "text": "Kairo taught music theory."}])
    choice = match_segue(TRACK, [nxt], 0.8)
    out = asyncio.run(rag.generate_transition(TRACK, choice, 0.8, "normal"))
    assert out["sourceEvents"] == ["evt_k"] and "Kairo taught music theory." in out["transitionScript"]
    assert "9A" in out["transitionScript"]
    minimal = asyncio.run(rag.generate_transition(TRACK, choice, 0.8, "minimal"))
    assert minimal["sourceEvents"] == []
