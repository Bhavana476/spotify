"""Authoritative in-memory lounge state: Now Playing / Next Up / Soundclash Stage, presence and roles.

Pure and synchronous: every mutation runs to completion inside one event-loop step, so no client can observe
a partially applied reorder. Each mutation bumps `version`; clients drop any snapshot older than one they hold.
"""
import itertools
import time
import uuid
from dataclasses import dataclass, field

POSITION_STEP = 1000
ROLE_RANK = {"listener": 0, "co_dj": 1, "host": 2, "admin": 3}
MIN_BATTLE, MAX_BATTLE = 2, 4


class QueueError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class QueueItem:
    entry_id: str
    track_id: str
    position: int
    added_by: int | None
    votes: set[int] = field(default_factory=set)
    locked_reason: str | None = None  # 'segue' | 'battle' | 'host' -> pinned ahead of vote order

    def to_dict(self, index: int) -> dict:
        return {"entryId": self.entry_id, "trackId": self.track_id, "position": index,
                "sparsePosition": self.position, "votes": len(self.votes), "voterIds": sorted(self.votes),
                "addedBy": self.added_by, "locked": self.locked_reason}


@dataclass
class Battle:
    battle_id: str
    candidates: list[dict]  # [{trackId, submittedBy, entryId|None}]
    opened_at: float
    closes_at: float
    opened_by: str
    votes: dict[int, str] = field(default_factory=dict)  # userId -> trackId
    status: str = "open"  # open | tied | resolved
    winning_track_id: str | None = None

    def tally(self) -> dict[str, int]:
        counts = {c["trackId"]: 0 for c in self.candidates}
        for track_id in self.votes.values():
            counts[track_id] += 1
        return counts

    def to_dict(self) -> dict:
        return {"battleId": self.battle_id, "candidateTrackIds": [c["trackId"] for c in self.candidates],
                "candidates": self.candidates, "closesAt": self.closes_at, "openedAt": self.opened_at,
                "openedBy": self.opened_by, "tally": self.tally(), "status": self.status,
                "winningTrackId": self.winning_track_id, "voteCount": len(self.votes)}


@dataclass
class Participant:
    user_id: int
    display_name: str
    joined_seq: int
    connections: int = 0
    rtt_ms: float | None = None
    muted: bool = False


class LoungeState:
    _seq = itertools.count(1)

    def __init__(self, lounge_id: str, host_user_id: int, settings: dict, clock=time.time):
        self.lounge_id = lounge_id
        self.host_user_id = host_user_id
        self.original_host_id = host_user_id
        self.settings = settings  # maxParticipants, bpmTolerancePct, soundclashEnabled, aiVerbosity, battleSeconds
        self.clock = clock
        self.status = "scheduled"
        self.locked = False
        self.frozen = False  # host gone and no co-DJ to promote: queue mutations rejected
        self.host_state = "connected"
        self.version = 0
        self.co_djs: set[int] = set()
        self.banned: set[int] = set()
        self.participants: dict[int, Participant] = {}
        self.now_playing: dict | None = None  # {entryId, trackId, startedAt}
        self.next_up: list[QueueItem] = []
        self.history: list[str] = []
        self.battle: Battle | None = None
        self.submissions: list[dict] = []  # pending Soundclash challengers [{trackId, submittedBy}]
        self.pending_segue: dict | None = None
        self.rejected_segues: set[str] = set()
        self.peak_participants = 0

    # ---------- roles & presence ----------
    def role_of(self, user_id: int, account_role: str = "listener") -> str:
        if account_role == "admin":
            return "admin"
        if user_id == self.host_user_id:
            return "host"
        if user_id in self.co_djs:
            return "co_dj"
        return "listener"

    def require(self, user_id: int, account_role: str, minimum: str):
        if ROLE_RANK[self.role_of(user_id, account_role)] < ROLE_RANK[minimum]:
            raise QueueError("forbidden", f"Requires lounge role '{minimum}' or higher")

    def connected_ids(self) -> list[int]:
        return [p.user_id for p in self.participants.values() if p.connections > 0]

    def connect(self, user_id: int, display_name: str) -> bool:
        """Returns True if this is a fresh join (False for a reconnect / second tab)."""
        if user_id in self.banned:
            raise QueueError("banned", "You were removed from this lounge")
        p = self.participants.get(user_id)
        fresh = p is None or p.connections == 0
        if fresh and user_id != self.host_user_id:
            if self.locked:
                raise QueueError("locked", "Lounge is locked by the host")
            if len(self.connected_ids()) >= self.settings.get("maxParticipants", 50):
                raise QueueError("full", "Lounge is at capacity")
        if p is None:
            p = self.participants[user_id] = Participant(user_id, display_name, next(self._seq))
        p.connections += 1
        if user_id == self.host_user_id and self.host_state != "connected":
            self.host_state = "connected"
            self.frozen = False
        self.peak_participants = max(self.peak_participants, len(self.connected_ids()))
        if fresh:
            self._bump()
        return fresh

    def drop_connection(self, user_id: int):
        p = self.participants.get(user_id)
        if p and p.connections > 0:
            p.connections -= 1

    def finalize_leave(self, user_id: int) -> dict | None:
        """Called after the reconnect grace period. Applies the deterministic host-disconnect policy:
        promote the longest-present connected Co-DJ; if none, freeze queue mutation until the host returns."""
        p = self.participants.get(user_id)
        if p is None or p.connections > 0:
            return None
        outcome = {"left": user_id}
        if user_id == self.host_user_id:
            candidates = sorted((self.participants[c] for c in self.co_djs
                                 if c in self.participants and self.participants[c].connections > 0),
                                key=lambda part: part.joined_seq)
            if candidates:
                new_host = candidates[0].user_id
                self.co_djs.discard(new_host)
                self.co_djs.add(user_id)
                self.host_user_id = new_host
                self.host_state = "connected"
                outcome["promotedHost"] = new_host
            else:
                self.host_state = "disconnected"
                self.frozen = True
                outcome["frozen"] = True
        self._bump()
        return outcome

    # ---------- queue ----------
    def _bump(self):
        self.version += 1

    def _sort(self):
        self.next_up.sort(key=lambda q: (q.locked_reason is None, -len(q.votes) if q.locked_reason is None else 0,
                                         q.position))

    def _guard_mutation(self):
        if self.frozen:
            raise QueueError("frozen", "Host disconnected — queue is frozen until they return")
        if self.status == "ended":
            raise QueueError("ended", "Lounge has ended")

    def _next_position(self) -> int:
        return (max((q.position for q in self.next_up), default=0)) + POSITION_STEP

    def _front_position(self) -> int:
        return (min((q.position for q in self.next_up), default=POSITION_STEP)) - POSITION_STEP

    def add_track(self, track_id: str, user_id: int | None, system: bool = False) -> QueueItem:
        if not system:  # the playback clock may refill an empty queue even while frozen
            self._guard_mutation()
        if any(q.track_id == track_id for q in self.next_up):
            raise QueueError("duplicate", "Track is already queued")
        item = QueueItem(_id("qe"), track_id, self._next_position(), user_id)
        self.next_up.append(item)
        self._sort()
        self._bump()
        return item

    def entry(self, entry_id: str) -> QueueItem:
        for q in self.next_up:
            if q.entry_id == entry_id:
                return q
        raise QueueError("not_found", "Queue entry not found")

    def vote(self, user_id: int, entry_id: str, up: bool = True) -> bool:
        """Idempotent per user. Returns True if the visible order changed."""
        self._guard_mutation()
        item = self.entry(entry_id)
        before = [q.entry_id for q in self.next_up]
        (item.votes.add if up else item.votes.discard)(user_id)
        self._sort()
        self._bump()
        return before != [q.entry_id for q in self.next_up]

    def promote(self, entry_id: str, reason: str = "host") -> QueueItem:
        """Pin an entry to the front. Only the moved row's sparse position changes."""
        self._guard_mutation()
        item = self.entry(entry_id)
        for q in self.next_up:
            if q.locked_reason and q is not item:
                q.locked_reason = None  # only one pinned slot: the previous pin rejoins vote order
        item.position = self._front_position()
        item.locked_reason = reason
        self._sort()
        self._bump()
        return item

    def remove(self, entry_id: str):
        self._guard_mutation()
        self.next_up.remove(self.entry(entry_id))
        self._bump()

    def start(self, seed_track_id: str):
        if self.now_playing is None:
            self.now_playing = {"entryId": _id("qe"), "trackId": seed_track_id, "startedAt": self.clock()}
        self.status = "live"
        self._bump()

    def advance(self) -> dict | None:
        """Moves the head of Next Up into Now Playing. Returns the finished now_playing record."""
        finished = self.now_playing
        if finished:
            self.history.append(finished["trackId"])
        self.pending_segue = None
        self.rejected_segues.clear()
        if self.next_up:
            head = self.next_up.pop(0)
            self.now_playing = {"entryId": head.entry_id, "trackId": head.track_id, "startedAt": self.clock(),
                                "voterIds": sorted(head.votes)}
        else:
            self.now_playing = None
        self._bump()
        return finished

    # ---------- soundclash ----------
    def submit_challenger(self, track_id: str, user_id: int) -> dict:
        self._guard_mutation()
        if not self.settings.get("soundclashEnabled", True):
            raise QueueError("disabled", "Soundclash is disabled in this lounge")
        if self.battle and self.battle.status != "resolved":
            raise QueueError("battle_active", "A Soundclash is already running — vote in it!")
        if any(s["trackId"] == track_id for s in self.submissions):
            raise QueueError("duplicate", "That track is already submitted")
        if self.next_up and self.next_up[0].track_id == track_id:
            raise QueueError("duplicate", "That track already holds the Next Up slot")
        if len(self.submissions) >= MAX_BATTLE - 1:
            raise QueueError("full", "Soundclash already has the maximum number of challengers")
        sub = {"trackId": track_id, "submittedBy": user_id}
        self.submissions.append(sub)
        self._bump()
        return sub

    def open_battle(self, opened_by: str, duration_seconds: float | None = None) -> Battle:
        self._guard_mutation()
        if self.battle and self.battle.status != "resolved":
            raise QueueError("battle_active", "A Soundclash is already running")
        candidates = []
        if self.next_up:  # the current Next Up slot defends
            head = self.next_up[0]
            candidates.append({"trackId": head.track_id, "submittedBy": head.added_by, "entryId": head.entry_id,
                               "defender": True})
        for s in self.submissions[:MAX_BATTLE - len(candidates)]:
            candidates.append({**s, "entryId": None, "defender": False})
        if len(candidates) < MIN_BATTLE:
            raise QueueError("not_enough", "A Soundclash needs at least 2 candidates")
        now = self.clock()
        duration = duration_seconds or self.settings.get("battleSeconds", 30)
        self.battle = Battle(_id("bt"), candidates, now, now + duration, opened_by)
        self.submissions = []
        self._bump()
        return self.battle

    def battle_vote(self, user_id: int, track_id: str):
        if not self.battle or self.battle.status == "resolved":
            raise QueueError("no_battle", "No Soundclash is open")
        if self.battle.status == "open" and self.clock() > self.battle.closes_at:
            raise QueueError("closed", "Voting has closed")
        if track_id not in {c["trackId"] for c in self.battle.candidates}:
            raise QueueError("invalid", "Not a candidate in this battle")
        if self.battle.status == "tied":
            raise QueueError("closed", "Voting closed — waiting for the host to break the tie")
        self.battle.votes[user_id] = track_id
        self._bump()

    def close_battle(self) -> str | None:
        """Closes voting. Returns the winner, or None if tied (status -> 'tied', host/AI must break it)."""
        b = self.battle
        if not b or b.status != "open":
            return None
        tally = b.tally()
        best = max(tally.values())
        leaders = [t for t, v in tally.items() if v == best]
        if len(leaders) == 1:
            return self.apply_battle_winner(leaders[0])
        b.status = "tied"
        self._bump()
        return None

    def tied_track_ids(self) -> list[str]:
        if not self.battle:
            return []
        tally = self.battle.tally()
        best = max(tally.values())
        return [t for t, v in tally.items() if v == best]

    def apply_battle_winner(self, track_id: str) -> str:
        b = self.battle
        if not b or b.status == "resolved":
            raise QueueError("no_battle", "No Soundclash to resolve")
        if track_id not in {c["trackId"] for c in b.candidates}:
            raise QueueError("invalid", "Winner must be one of the candidates")
        if b.status == "tied" and track_id not in self.tied_track_ids():
            raise QueueError("invalid", "Tie-break must pick one of the tied leaders")
        b.status, b.winning_track_id = "resolved", track_id
        existing = next((q for q in self.next_up if q.track_id == track_id), None)
        if existing is None:
            winner_by = next(c["submittedBy"] for c in b.candidates if c["trackId"] == track_id)
            existing = QueueItem(_id("qe"), track_id, self._front_position(), winner_by)
            self.next_up.append(existing)
        # Splice: the winner takes the Next Up slot; the defeated defender keeps its place behind it.
        for q in self.next_up:
            if q.locked_reason and q is not existing:
                q.locked_reason = None
        existing.position = self._front_position()
        existing.locked_reason = "battle"
        self._sort()
        self._bump()
        return track_id

    # ---------- snapshots ----------
    def queue_view(self) -> list[dict]:
        return [q.to_dict(i) for i, q in enumerate(self.next_up)]

    def snapshot(self, account_roles: dict[int, str] | None = None) -> dict:
        account_roles = account_roles or {}
        return {
            "loungeId": self.lounge_id, "version": self.version, "status": self.status,
            "hostUserId": self.host_user_id, "hostState": self.host_state, "frozen": self.frozen,
            "locked": self.locked, "coDjIds": sorted(self.co_djs), "settings": self.settings,
            "nowPlaying": self.now_playing, "queue": self.queue_view(),
            "soundclash": self.battle.to_dict() if self.battle and self.battle.status != "resolved" else None,
            "lastBattle": self.battle.to_dict() if self.battle and self.battle.status == "resolved" else None,
            "submissions": self.submissions, "pendingSegue": self.pending_segue, "history": self.history[-10:],
            "participants": [{"userId": p.user_id, "displayName": p.display_name, "rttMs": p.rtt_ms,
                              "muted": p.muted, "role": self.role_of(p.user_id, account_roles.get(p.user_id,
                                                                                                   "listener"))}
                             for p in self.participants.values() if p.connections > 0],
            "serverTime": self.clock(),
        }
