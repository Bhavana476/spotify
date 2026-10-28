"""Chat sentiment: a lexicon scorer tuned for party/DJ chat plus a rolling-window room aggregator.

A lexicon is used deliberately: it is deterministic, sub-millisecond per message (chat bursts never block
the event loop), and its decisions are explainable. Accuracy is measured in tests/test_sentiment.py.
"""
import re
import time
from collections import deque

POSITIVE = {
    "love": 2, "loving": 2, "lovely": 1.5, "amazing": 2, "awesome": 2, "banger": 2.5, "bangers": 2.5, "fire": 2,
    "lit": 2, "hype": 1.5, "hyped": 2, "vibe": 1, "vibes": 1, "vibing": 1.5, "great": 1.5, "good": 1, "nice": 1,
    "dope": 2, "sick": 1.5, "insane": 1.5, "epic": 2, "perfect": 2, "best": 1.5, "yes": 1, "yess": 1.5,
    "yesss": 2, "lets": 0.5, "go": 0.5, "dance": 1.5, "dancing": 1.5, "groove": 1.5, "groovy": 1.5,
    "energy": 1, "louder": 1.5, "drop": 1, "goosebumps": 2, "obsessed": 2, "incredible": 2, "beautiful": 1.5,
    "smooth": 1, "chill": 0.5, "wow": 1.5, "woo": 2, "woohoo": 2, "party": 1.5, "anthem": 2, "classic": 1,
    "favorite": 1.5, "favourite": 1.5, "slaps": 2.5, "slap": 1.5, "bop": 2, "jam": 1.5, "killer": 1.5,
    "excellent": 2, "fun": 1.5, "happy": 1.5, "brilliant": 2, "cool": 1, "wild": 1, "unreal": 1.5, "gem": 1.5,
    "masterpiece": 2.5, "goated": 2.5, "heat": 1.5, "hot": 1, "up": 0.3, "more": 0.5, "again": 0.5,
    "keep": 0.3, "turn": 0.2, "feel": 0.3, "feeling": 0.3, "legendary": 2.5, "thanks": 1, "thank": 1,
}
NEGATIVE = {
    "boring": -2, "bored": -2, "meh": -1.5, "bad": -1.5, "awful": -2.5, "terrible": -2.5, "hate": -2.5,
    "trash": -2.5, "garbage": -2.5, "worst": -2.5, "skip": -2, "next": -1, "sleepy": -1.5, "tired": -1.5,
    "slow": -1, "dead": -2, "dying": -1, "lame": -2, "cringe": -2, "annoying": -2, "ugh": -1.5, "nope": -1.5,
    "stop": -1.5, "off": -0.5, "clash": -1.5, "offbeat": -2, "jarring": -2, "sucks": -2.5, "suck": -2,
    "mid": -1.5, "flat": -1, "dull": -2, "snooze": -2, "yawn": -2, "leave": -1.5, "leaving": -1.5,
    "quiet": -0.5, "ruin": -2, "ruined": -2, "kill": -1, "killed": -1, "worse": -2, "horrible": -2.5,
    "painful": -2, "weird": -1, "wrong": -1.5, "nah": -1.5, "tedious": -2, "zzz": -2, "asleep": -2,
    "repetitive": -1.5, "change": -1, "disappointing": -2, "disappointed": -2, "sad": -1, "overplayed": -1.5,
}
EMOJI = {
    "🔥": 2, "💯": 2, "🎉": 2, "🙌": 2, "😍": 2, "🥳": 2, "💃": 2, "🕺": 2, "❤": 1.5, "❤️": 1.5, "😎": 1.5,
    "🤩": 2, "👏": 1.5, "⚡": 1.5, "🎶": 1, "😀": 1, "😄": 1.5, "👍": 1, ":)": 1, ":d": 1.5,
    "😴": -2, "🥱": -2, "👎": -2, "😒": -1.5, "🙄": -1.5, "💤": -2, "😩": -1.5, "😕": -1, "🤮": -2.5,
    "😐": -0.5, ":(": -1.5,
}
NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "aint", "ain't", "wasnt", "wasn't",
            "cant", "can't", "doesnt", "doesn't", "nothing"}
INTENSIFIERS = {"so": 1.4, "very": 1.4, "really": 1.3, "super": 1.5, "absolutely": 1.6, "totally": 1.4,
                "extremely": 1.6, "insanely": 1.6, "too": 1.2}
# Phrases override token scoring where word-level polarity misleads.
PHRASES = {"turn it up": 2, "turn up": 2, "lets go": 2.5, "let's go": 2.5, "go off": 2, "on repeat": 2,
           "turn it off": -2.5, "change the song": -2.5, "kill me": -1.5, "not feeling": -2,
           "falling asleep": -2.5, "too slow": -2, "energy is dead": -3, "killing it": 2.5, "kills it": 2,
           "so dead": -2.5, "next please": -2, "make it stop": -2.5, "no skip": 2, "dont skip": 2,
           "don't skip": 2, "not bad": 1, "who cares": -1.5}
_TOKEN_RE = re.compile(r"[a-z']+|:\)|:\(|:d|[^\w\s]", re.UNICODE)
POSITIVE_THRESHOLD, NEGATIVE_THRESHOLD = 0.5, -0.5


def score_message(text: str) -> float:
    """Raw polarity in [-1, 1]."""
    lowered = text.lower()
    total = 0.0
    for phrase, value in PHRASES.items():
        if phrase in lowered:
            total += value
            lowered = lowered.replace(phrase, " ")
    tokens = _TOKEN_RE.findall(lowered)
    for i, tok in enumerate(tokens):
        base = POSITIVE.get(tok) or NEGATIVE.get(tok) or EMOJI.get(tok)
        if not base:
            # collapse elongations: "sooo goooood" -> "so good"
            squashed = re.sub(r"(.)\1{2,}", r"\1\1", tok)
            base = POSITIVE.get(squashed) or NEGATIVE.get(squashed) or POSITIVE.get(re.sub(r"(.)\1+", r"\1", tok))
        if not base:
            continue
        window = tokens[max(0, i - 3):i]
        if any(w in NEGATORS for w in window):
            base = -base * 0.8
        if i > 0 and tokens[i - 1] in INTENSIFIERS:
            base *= INTENSIFIERS[tokens[i - 1]]
        total += base
    exclaims = text.count("!")
    if total and exclaims:
        total *= 1 + min(exclaims, 3) * 0.1
    if text.isupper() and len(text) > 3 and total:
        total *= 1.2
    return max(-1.0, min(1.0, total / 3.0))


def bucket(score: float) -> str:
    """Maps raw polarity to the three energy buckets used throughout the system."""
    if score >= POSITIVE_THRESHOLD / 3:
        return "positive"
    if score <= NEGATIVE_THRESHOLD / 3:
        return "negative"
    return "neutral"


def classify(text: str) -> tuple[str, float]:
    s = score_message(text)
    return bucket(s), s


class RollingSentiment:
    """Room-level score over a sliding time window. Output is 0..1 where 0.5 is neutral."""

    def __init__(self, window_seconds: float = 30.0, clock=time.time):
        self.window_seconds = window_seconds
        self.clock = clock
        self.samples: deque[tuple[float, float]] = deque()

    def add(self, raw_score: float, ts: float | None = None):
        self.samples.append((ts if ts is not None else self.clock(), raw_score))
        self._evict()

    def _evict(self):
        cutoff = self.clock() - self.window_seconds
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def score(self) -> float:
        self._evict()
        if not self.samples:
            return 0.5
        now = self.clock()
        # Newer messages weigh more (linear decay to 0.3 at the window edge).
        weights = [1.0 - 0.7 * (now - ts) / self.window_seconds for ts, _ in self.samples]
        mean = sum(w * s for w, (_, s) in zip(weights, self.samples)) / sum(weights)
        return round(0.5 + mean / 2, 4)

    def snapshot(self) -> dict:
        return {"rollingScore": self.score(), "windowSeconds": self.window_seconds,
                "sampleSize": len(self.samples)}
