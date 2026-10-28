"""RAG over authored track metadata timelines: transition banter + listener Q&A.

Retrieval is lexical over the track's own timeline entries (tiny corpus per track, so no vector index is
needed). Generation uses Claude when ANTHROPIC_API_KEY is set, constrained to the retrieved entries and
verified afterwards; otherwise, or on timeout/failure, a deterministic template composes the answer from the
same entries. Either way every response carries the ids of the entries it used.
"""
import asyncio
import logging
import re

from .. import config
from .acoustic import SegueCandidate, TrackProfile

log = logging.getLogger("djstudio.rag")

_STOP = {"the", "a", "an", "is", "are", "was", "were", "what", "whats", "what's", "where", "wheres", "who",
         "how", "this", "that", "it", "its", "it's", "of", "on", "in", "to", "for", "track", "song", "tune",
         "about", "from", "me", "tell", "do", "does", "did", "you", "know", "any", "and", "or", "with", "be",
         "can", "i", "dj", "playing", "now", "current", "one", "there", "here", "by", "at", "has", "have"}
TYPE_HINTS = {
    "sample_credit": {"sample", "sampled", "samples", "sampling", "chop", "vocal", "vocals", "loop", "origin",
                      "flip", "flipped", "borrowed", "credit", "credits"},
    "artist_bio": {"artist", "producer", "produced", "made", "maker", "who", "behind", "band", "group",
                   "background", "bio"},
    "trivia": {"trivia", "fact", "facts", "story", "recorded", "studio", "session", "fun", "history",
               "behind", "made", "when", "written", "wrote"},
    "glossary": {"mean", "means", "meaning", "term", "genre", "style", "define", "definition"},
}
_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1}


def retrieve(question: str, track: TrackProfile, k: int = 2) -> list[dict]:
    raw = set(_WORD.findall(question.lower()))
    q = _tokens(question)
    scored = []
    for entry in track.timeline:
        overlap = len(q & _tokens(entry["text"]))
        type_boost = 1.5 if raw & TYPE_HINTS.get(entry["type"], set()) else 0.0
        score = overlap + type_boost
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["ts"]))
    return [entry for _, entry in scored[:k]]


async def _llm(system: str, prompt: str, max_tokens: int = 200) -> str | None:
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = await asyncio.wait_for(
            client.messages.create(model=config.LLM_MODEL, max_tokens=max_tokens, system=system,
                                   messages=[{"role": "user", "content": prompt}]),
            timeout=config.LLM_TIMEOUT_SECONDS)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip() or None
    except Exception as exc:  # timeout, network, auth: fall back to the template path
        log.warning("LLM call failed, using template fallback: %s", exc)
        return None


_GROUNDING_RULES = ("You are the AI DJ in a live listening room. Use ONLY the numbered facts provided. "
                    "Never add names, dates, places or details that are not in the facts. "
                    "Cite each fact you use inline as [id]. Max 2 sentences, casual DJ voice.")


def _verify_citations(text: str, allowed: list[dict]) -> list[str] | None:
    """Returns cited ids if every citation is one of the retrieved entries and at least one is present."""
    allowed_ids = {e["id"] for e in allowed}
    cited = re.findall(r"\[(\w+)\]", text)
    if not cited or any(c not in allowed_ids for c in cited):
        return None
    return list(dict.fromkeys(cited))


async def answer_question(question: str, track: TrackProfile) -> dict:
    entries = retrieve(question, track)
    if not entries:
        return {"answer": f"I don't have anything in my notes on that for \"{track.title}\" — I'd rather "
                          f"not guess. Ask me about its samples, the artist, or the story behind it.",
                "sourceEvents": [], "grounded": False, "trackId": track.id, "generator": "template"}
    facts = "\n".join(f"[{e['id']}] ({e['type']}) {e['text']}" for e in entries)
    llm_text = await _llm(_GROUNDING_RULES, f"Track: \"{track.title}\" by {track.artist}\nFacts:\n{facts}\n\n"
                                            f"Listener question: {question}")
    if llm_text:
        cited = _verify_citations(llm_text, entries)
        if cited:
            clean = re.sub(r"\s*\[\w+\]", "", llm_text).strip()
            return {"answer": clean, "sourceEvents": cited, "grounded": True, "trackId": track.id,
                    "generator": "llm"}
    lead = entries[0]
    answer = f"On \"{track.title}\" by {track.artist}: {lead['text']}"
    if len(entries) > 1:
        answer += f" Also — {entries[1]['text']}"
    return {"answer": answer, "sourceEvents": [e["id"] for e in entries], "grounded": True,
            "trackId": track.id, "generator": "template"}


def _pick_fact(track: TrackProfile, count: int) -> list[dict]:
    order = {"sample_credit": 0, "artist_bio": 1, "trivia": 2, "glossary": 3}
    return sorted(track.timeline, key=lambda e: (order.get(e["type"], 9), e["ts"]))[:count]


def _template_transition(current: TrackProfile, choice: SegueCandidate, sentiment: float,
                         facts: list[dict]) -> str:
    nxt = choice.track
    if sentiment >= 0.62:
        mood = "Room's on fire — keeping the energy climbing"
    elif sentiment <= 0.4:
        mood = "Feeling the room needs a reset — easing the pace"
    else:
        mood = "Smooth handoff coming up"
    relation = {"identical": f"locked in the same key, {nxt.camelot_key}",
                "relative": f"flipping to the relative {'major' if nxt.camelot_key.endswith('B') else 'minor'}, "
                            f"{nxt.camelot_key}",
                "adjacent": f"stepping one notch round the wheel to {nxt.camelot_key}"}[choice.camelot_relation]
    tempo = {"same": f"at {nxt.bpm:g} BPM", "half_time": f"dropping into half-time at {nxt.bpm:g} BPM",
             "double_time": f"doubling up to {nxt.bpm:g} BPM"}[choice.bpm_relation]
    line = f"{mood}: out of \"{current.title}\" into \"{nxt.title}\" by {nxt.artist}, {relation}, {tempo}."
    for fact in facts:
        line += f" Fun fact: {fact['text']}"
    return line


async def generate_transition(current: TrackProfile, choice: SegueCandidate, sentiment: float,
                              verbosity: str = "normal") -> dict:
    facts = _pick_fact(choice.track, {"minimal": 0, "normal": 1, "chatty": 2}.get(verbosity, 1))
    script = _template_transition(current, choice, sentiment, facts)
    generator = "template"
    if facts and verbosity != "minimal":
        fact_lines = "\n".join(f"[{f['id']}] {f['text']}" for f in facts)
        llm_text = await _llm(_GROUNDING_RULES,
                              f"Write a transition line from \"{current.title}\" into \"{choice.track.title}\" by "
                              f"{choice.track.artist}. Musical reason: key {choice.camelot_relation} "
                              f"({current.camelot_key}->{choice.track.camelot_key}), tempo {choice.bpm_relation} "
                              f"({current.bpm:g}->{choice.track.bpm:g} BPM). Room sentiment {sentiment:.2f} "
                              f"(0=flat, 1=hyped).\nFacts:\n{fact_lines}", max_tokens=120)
        if llm_text and _verify_citations(llm_text, facts):
            script = re.sub(r"\s*\[\w+\]", "", llm_text).strip()
            generator = "llm"
    return {"transitionScript": script, "sourceEvents": [f["id"] for f in facts], "generator": generator}


def battle_banter(winner: TrackProfile, votes: int, total: int) -> tuple[str, list[str]]:
    facts = _pick_fact(winner, 1)
    line = f"Soundclash settled! \"{winner.title}\" by {winner.artist} takes it with {votes} of {total} votes."
    if facts:
        line += f" {facts[0]['text']}"
    return line, [f["id"] for f in facts]
