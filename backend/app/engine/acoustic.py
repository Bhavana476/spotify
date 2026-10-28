"""Acoustic feature matching (PRD 6.2). BPM and Camelot rules are hard constraints; ranking is 50/30/20."""
import re
from dataclasses import dataclass, field

CAMELOT_KEYS = tuple(f"{n}{letter}" for n in range(1, 13) for letter in "AB")
_KEY_RE = re.compile(r"^(1[0-2]|[1-9])([AB])$")

HARMONIC_CLOSENESS = {"identical": 1.0, "relative": 0.85, "adjacent": 0.75}
WEIGHT_HARMONIC, WEIGHT_ENERGY, WEIGHT_RECENCY = 0.5, 0.3, 0.2
TEMPO_MULTIPLES = ((1.0, "same"), (0.5, "half_time"), (2.0, "double_time"))


@dataclass
class TrackProfile:
    id: str
    title: str
    artist: str
    duration_seconds: int
    bpm: float
    camelot_key: str
    energy: float
    valence: float
    timeline: list[dict] = field(default_factory=list)  # [{id, ts, type, text}]


def parse_camelot(key: str) -> tuple[int, str]:
    match = _KEY_RE.match(key.strip().upper()) if isinstance(key, str) else None
    if not match:
        raise ValueError(f"'{key}' is not a valid Camelot key (expected 1A-12B)")
    return int(match.group(1)), match.group(2)


def camelot_relation(current: str, candidate: str) -> str | None:
    """'identical' | 'adjacent' | 'relative' | None (clash)."""
    n1, l1 = parse_camelot(current)
    n2, l2 = parse_camelot(candidate)
    if n1 == n2 and l1 == l2:
        return "identical"
    if n1 == n2:
        return "relative"
    if l1 == l2 and (n1 - n2) % 12 in (1, 11):  # wheel wraps 12 <-> 1
        return "adjacent"
    return None


def bpm_relation(current_bpm: float, candidate_bpm: float, tolerance_pct: float = 8.0):
    """Returns (relation, delta_pct) for the closest valid tempo multiple, or None if out of tolerance."""
    best = None
    for multiple, name in TEMPO_MULTIPLES:
        target = current_bpm * multiple
        delta_pct = abs(candidate_bpm - target) / target * 100
        if delta_pct <= tolerance_pct + 1e-9 and (best is None or delta_pct < best[1]):
            best = (name, round(delta_pct, 2))
    return best


def is_valid_segue(current: TrackProfile, candidate: TrackProfile, tolerance_pct: float = 8.0) -> bool:
    return (candidate.id != current.id
            and bpm_relation(current.bpm, candidate.bpm, tolerance_pct) is not None
            and camelot_relation(current.camelot_key, candidate.camelot_key) is not None)


def target_energy(current_energy: float, sentiment: float) -> float:
    """Sentiment is 0..1 (0.5 neutral). Positive rooms push energy up, fatigued rooms pull it back."""
    return min(1.0, max(0.0, current_energy + (sentiment - 0.5) * 0.5))


@dataclass
class SegueCandidate:
    track: TrackProfile
    score: float
    bpm_relation: str
    bpm_delta_pct: float
    camelot_relation: str
    harmonic_closeness: float
    energy_fit: float
    recency: float

    def match_reason(self) -> dict:
        return {"bpmDeltaPct": self.bpm_delta_pct, "bpmRelation": self.bpm_relation,
                "camelotRelation": self.camelot_relation, "energyFit": round(self.energy_fit, 2),
                "harmonicCloseness": self.harmonic_closeness, "recency": self.recency,
                "score": round(self.score, 4)}


def rank_segues(current: TrackProfile, candidates: list[TrackProfile], sentiment: float = 0.5,
                recent_ids: list[str] | None = None, tolerance_pct: float = 8.0) -> list[SegueCandidate]:
    """Filters to rule-valid candidates only, then ranks. Invalid candidates can never be returned."""
    recent = set(recent_ids or [])
    goal = target_energy(current.energy, sentiment)
    ranked: list[SegueCandidate] = []
    seen: set[str] = set()
    for cand in candidates:
        if cand.id in seen or cand.id == current.id:
            continue
        seen.add(cand.id)
        bpm = bpm_relation(current.bpm, cand.bpm, tolerance_pct)
        key = camelot_relation(current.camelot_key, cand.camelot_key)
        if bpm is None or key is None:
            continue
        closeness = HARMONIC_CLOSENESS[key]
        energy_fit = 1.0 - abs(cand.energy - goal)
        recency = 0.0 if cand.id in recent else 1.0
        score = WEIGHT_HARMONIC * closeness + WEIGHT_ENERGY * energy_fit + WEIGHT_RECENCY * recency
        ranked.append(SegueCandidate(cand, score, bpm[0], bpm[1], key, closeness, energy_fit, recency))
    ranked.sort(key=lambda c: (-c.score, c.bpm_delta_pct, c.track.id))
    return ranked


def match_segue(current, candidates, sentiment=0.5, recent_ids=None, tolerance_pct=8.0) -> SegueCandidate | None:
    ranked = rank_segues(current, candidates, sentiment, recent_ids, tolerance_pct)
    return ranked[0] if ranked else None
