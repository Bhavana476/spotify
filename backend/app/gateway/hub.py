"""Queue & State Gateway: one Runtime per live lounge (state machine + sockets + sentiment + playback clock).

Many lounges run concurrently; nothing here assumes a single room.
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import WebSocket

from .. import catalog, config
from ..db import SessionLocal
from ..engine import dj, rag
from ..engine.sentiment import EMOJI, RollingSentiment, classify
from ..events import sink
from ..models import Lounge, QueueEntry, SoundclashBattle, SoundclashCandidate
from ..security import sanitize_text
from .lounge_state import LoungeState, QueueError

log = logging.getLogger("djstudio.gateway")
TICK_SECONDS = 0.25
SENTIMENT_TICK_SECONDS = 2.0
AUTO_BATTLE_DELAY = 8.0  # AI DJ opens a battle this long after the first challenger arrives
TIE_BREAK_GRACE = 15.0   # host has this long to break a tie before the AI does
ALLOWED_REACTIONS = {"🔥", "❤️", "🙌", "😂", "😴", "👎", "💯", "🎉"}


def _ms() -> int:
    return int(time.time() * 1000)


class Runtime:
    def __init__(self, lounge: Lounge):
        self.lounge_id = lounge.id
        self.seed_track_id = lounge.seed_track_id
        self.state = LoungeState(lounge.id, lounge.host_user_id, {
            "maxParticipants": lounge.max_participants, "bpmTolerancePct": lounge.bpm_tolerance_pct,
            "soundclashEnabled": lounge.soundclash_enabled, "aiVerbosity": lounge.ai_verbosity,
            "vibeProfile": lounge.vibe_profile, "battleSeconds": 30, "playbackSpeed": config.PLAYBACK_SPEED,
            "outroWindowSeconds": config.OUTRO_WINDOW_SECONDS, "inviteCode": lounge.invite_code})
        self.sockets: dict[WebSocket, int] = {}
        self.account_roles: dict[int, str] = {}
        self.token_exp: dict[WebSocket, float] = {}
        self.sentiment = RollingSentiment(config.SENTIMENT_WINDOW_SECONDS)
        self.chat_log: deque = deque(maxlen=100)
        self.ai_feed: deque = deque(maxlen=30)
        self.leave_timers: dict[int, asyncio.Task] = {}
        self.listen_since: dict[int, float] = {}
        self.liked_current: set[int] = set()
        self.segue_inflight = False
        self.first_submission_at: float | None = None
        self.last_sentiment_tick = 0.0
        self.last_sentiment_sent: float | None = None
        self.last_presence_tick = 0.0
        self.ai_latencies: list[float] = []
        self.task: asyncio.Task | None = None
        if lounge.status == "ended":
            self.state.status = "ended"

    # ---------- fan-out ----------
    async def broadcast(self, event: str, payload: dict):
        envelope = {"event": event, "loungeId": self.lounge_id, "payload": payload, "ts": _ms(),
                    "version": self.state.version}
        dead = []
        sockets = list(self.sockets)
        results = await asyncio.gather(*(ws.send_json(envelope) for ws in sockets), return_exceptions=True)
        for ws, result in zip(sockets, results):
            if isinstance(result, Exception):
                dead.append(ws)
        for ws in dead:
            self.sockets.pop(ws, None)

    async def push_state(self, reason: str):
        payload = self.state.snapshot(self.account_roles)
        payload["reason"] = reason
        payload["sentiment"] = self.sentiment.snapshot()
        await self.broadcast("lounge.queue.update", payload)

    def welcome(self) -> dict:
        payload = self.state.snapshot(self.account_roles)
        payload.update(reason="sync", sentiment=self.sentiment.snapshot(), chatHistory=list(self.chat_log),
                       aiFeed=list(self.ai_feed))
        return payload

    # ---------- presence ----------
    async def on_connect(self, ws: WebSocket, user_id: int, name: str, account_role: str, token_exp: float):
        fresh = self.state.connect(user_id, name)
        self.sockets[ws] = user_id
        self.account_roles[user_id] = account_role
        self.token_exp[ws] = token_exp
        timer = self.leave_timers.pop(user_id, None)
        if timer:
            timer.cancel()
        await ws.send_json({"event": "lounge.sync.state", "loungeId": self.lounge_id, "payload": self.welcome(),
                            "ts": _ms(), "version": self.state.version})
        if fresh:
            self.listen_since[user_id] = time.time()
            count = len(self.state.connected_ids())
            sink.event(self.lounge_id, "presence", {"action": "joined", "participantCount": count}, user_id)
            await self.broadcast("lounge.presence.update", {"participantId": user_id, "displayName": name,
                                                            "action": "joined", "participantCount": count})
            await self.push_state("presence")

    async def on_disconnect(self, ws: WebSocket):
        user_id = self.sockets.pop(ws, None)
        self.token_exp.pop(ws, None)
        if user_id is None:
            return
        self.state.drop_connection(user_id)
        if user_id not in self.state.connected_ids():
            # Grace window: a quick reconnect resumes silently with no duplicate join/leave events.
            self.leave_timers[user_id] = asyncio.create_task(self._leave_after_grace(user_id))

    async def _leave_after_grace(self, user_id: int):
        await asyncio.sleep(config.RECONNECT_GRACE_SECONDS)
        self.leave_timers.pop(user_id, None)
        outcome = self.state.finalize_leave(user_id)
        if outcome is None:
            return
        count = len(self.state.connected_ids())
        sink.event(self.lounge_id, "presence", {"action": "left", "participantCount": count, **outcome}, user_id)
        await self.broadcast("lounge.presence.update", {"participantId": user_id, "action": "left",
                                                        "participantCount": count})
        if outcome.get("promotedHost"):
            await self.system_message(f"Host disconnected — Co-DJ promoted to host.")
        elif outcome.get("frozen"):
            await self.system_message("Host disconnected — queue is frozen until they reconnect.")
        await self.push_state("host" if user_id == self.state.original_host_id else "presence")

    # ---------- chat & AI feed ----------
    async def system_message(self, text: str, msg_type: str = "system", extra: dict | None = None):
        msg = {"messageId": f"msg_{uuid.uuid4().hex[:10]}", "userId": None, "displayName": "AI DJ"
               if msg_type != "system" else "System", "body": text, "msgType": msg_type,
               "sentimentBucket": None, "tsSeconds": time.time(), **(extra or {})}
        self.chat_log.append(msg)
        sink.chat(msg["messageId"], self.lounge_id, None, msg_type, text, None, msg["tsSeconds"])
        await self.broadcast("lounge.chat.message", msg)

    async def announce(self, text: str, related_track_id: str | None, source_events: list[str], kind: str):
        item = {"text": text, "relatedTrackId": related_track_id, "sourceEvents": source_events, "kind": kind,
                "ts": time.time()}
        self.ai_feed.append(item)
        sink.chat(f"msg_{uuid.uuid4().hex[:10]}", self.lounge_id, None, "dj_announcement", text, None, item["ts"])
        await self.broadcast("lounge.ai.dj_announcement", item)

    # ---------- playback / AI loop ----------
    def start_loop(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())

    def remaining_seconds(self) -> float | None:
        np = self.state.now_playing
        track = catalog.get(np["trackId"]) if np else None
        if not track:
            return None
        elapsed = (time.time() - np["startedAt"]) * config.PLAYBACK_SPEED
        return track.duration_seconds - elapsed

    async def _loop(self):
        while self.state.status == "live":
            try:
                await self._tick()
            except Exception:
                log.exception("tick failed", extra={"loungeId": self.lounge_id})
            await asyncio.sleep(TICK_SECONDS)

    async def _tick(self):
        st, now = self.state, time.time()
        remaining = self.remaining_seconds()
        if st.now_playing is None:
            await self.advance_track()
        elif remaining is not None:
            if remaining <= config.OUTRO_WINDOW_SECONDS and st.pending_segue is None and not self.segue_inflight \
                    and not st.frozen:
                asyncio.create_task(self.run_segue("outro"))
            if remaining <= 0 and not self.segue_inflight:
                await self.advance_track()
        b = st.battle
        if b and b.status == "open" and now >= b.closes_at:
            winner = st.close_battle()
            await (self._battle_resolved(winner) if winner else self._battle_tied())
        elif b and b.status == "tied" and now >= b.closes_at + TIE_BREAK_GRACE:
            current = catalog.get(st.now_playing["trackId"]) if st.now_playing else None
            tied = [catalog.get(t) for t in st.tied_track_ids()]
            choice = dj.break_tie(current, [t for t in tied if t], self.sentiment.score(),
                                  st.settings["bpmTolerancePct"])
            await self._battle_resolved(st.apply_battle_winner(choice), tie_break="ai")
        if st.submissions and not (b and b.status != "resolved") and not st.frozen:
            self.first_submission_at = self.first_submission_at or now
            if now - self.first_submission_at >= AUTO_BATTLE_DELAY:
                await self.open_battle("ai_dj")
        if now - self.last_sentiment_tick >= SENTIMENT_TICK_SECONDS:
            self.last_sentiment_tick = now
            snap = self.sentiment.snapshot()
            if snap["rollingScore"] != self.last_sentiment_sent:
                self.last_sentiment_sent = snap["rollingScore"]
                sink.event(self.lounge_id, "sentimentTick", snap)
                await self.broadcast("lounge.sentiment.score", snap)
        if now - self.last_presence_tick >= 5:
            self.last_presence_tick = now
            await self.broadcast("lounge.presence.list", {"participants": st.snapshot(self.account_roles)
                                                          ["participants"]})

    async def run_segue(self, trigger: str) -> dict | None:
        st = self.state
        if self.segue_inflight or not st.now_playing:
            return None
        self.segue_inflight = True
        try:
            current = catalog.get(st.now_playing["trackId"])
            head = st.next_up[0] if st.next_up else None
            locked = catalog.get(head.track_id) if head and head.locked_reason in ("battle", "host") else None
            decision = await dj.decide_segue(
                current, [t for t in (catalog.get(q.track_id) for q in st.next_up) if t], catalog.all_tracks(),
                self.sentiment.score(), st.history[-5:] + [current.id], st.settings["bpmTolerancePct"],
                st.settings["aiVerbosity"], locked=locked, exclude_ids=st.rejected_segues)
            if decision is None:
                await self.announce("No harmonically safe segue in the crate — the queue plays on as-is.",
                                    None, [], "segue")
                st.pending_segue = {"selectedTrackId": None, "aiSelected": False}
                return None
            if not st.frozen and st.status == "live":
                if decision["fromCatalog"]:
                    st.add_track(decision["selectedTrackId"], None)
                if locked is None:
                    entry = next(q for q in st.next_up if q.track_id == decision["selectedTrackId"])
                    st.promote(entry.entry_id, "segue")
            decision["trigger"] = trigger
            decision["status"] = "pending"
            st.pending_segue = decision
            self.ai_latencies.append(decision["latencyMs"])
            event_id = sink.event(self.lounge_id, "segue", {"fromTrackId": current.id, **decision})
            decision["eventId"] = event_id
            log.info("ai_segue", extra={"loungeId": self.lounge_id, "latencyMs": decision["latencyMs"],
                                        "selected": decision["selectedTrackId"], "aiSelected": decision["aiSelected"]})
            await self.push_state("segue")
            await self.announce(decision["transitionScript"], decision["selectedTrackId"], decision["sourceEvents"],
                                "segue")
            return decision
        finally:
            self.segue_inflight = False

    async def advance_track(self):
        st = self.state
        finished = st.advance()
        if finished:
            self._record_listens(finished)
        if st.now_playing is None:
            # Empty queue: the AI DJ digs a valid segue from the crate so the room never goes silent.
            last = catalog.get(finished["trackId"]) if finished else catalog.get(self.seed_track_id)
            decision = await dj.decide_segue(last, [], catalog.all_tracks(), self.sentiment.score(),
                                             st.history[-5:], st.settings["bpmTolerancePct"], "minimal") if last else None
            st.add_track(decision["selectedTrackId"] if decision else self.seed_track_id, None, system=True)
            st.advance()
        self.liked_current = set()
        now = time.time()
        for uid in st.connected_ids():
            self.listen_since[uid] = now
        sink.event(self.lounge_id, "nowPlaying", {"trackId": st.now_playing["trackId"]})
        await self.push_state("advance")

    def _record_listens(self, finished: dict):
        track = catalog.get(finished["trackId"])
        if not track:
            return
        present = self.state.connected_ids()
        voters = set(finished.get("voterIds", []))
        for uid in present:
            since = max(self.listen_since.get(uid, finished["startedAt"]), finished["startedAt"])
            played = min(track.duration_seconds, (time.time() - since) * config.PLAYBACK_SPEED)
            sink.interaction(user_id=uid, track_id=track.id, lounge_id=self.lounge_id, played_seconds=played,
                             completed=played >= track.duration_seconds * 0.8,
                             liked=uid in voters or uid in self.liked_current,
                             co_listened_with=[o for o in present if o != uid])
        sink.event(self.lounge_id, "trackPlayed", {"trackId": track.id, "listeners": present})

    # ---------- soundclash ----------
    async def open_battle(self, opened_by: str):
        battle = self.state.open_battle(opened_by)
        self.first_submission_at = None
        sink.event(self.lounge_id, "battleOpened", {"battleId": battle.battle_id,
                                                    "candidateTrackIds": [c["trackId"] for c in battle.candidates]})
        await self.broadcast("lounge.soundclash.open", {"battleId": battle.battle_id,
                                                        "candidateTrackIds": [c["trackId"] for c in battle.candidates],
                                                        "closesAt": battle.closes_at})
        await self.push_state("battle")

    async def _battle_tied(self):
        await self.system_message("Soundclash is tied! Host or Co-DJ: break the tie, or the AI DJ will in "
                                  f"{int(TIE_BREAK_GRACE)}s.")
        await self.push_state("battle")

    async def _battle_resolved(self, winner_id: str, tie_break: str | None = None):
        b = self.state.battle
        tally = b.tally()
        sink.event(self.lounge_id, "battleResolved", {"battleId": b.battle_id, "winningTrackId": winner_id,
                                                      "tally": tally, "tieBreak": tie_break})
        sink.records(
            SoundclashBattle(id=b.battle_id, lounge_id=self.lounge_id, status="resolved", winning_track_id=winner_id,
                             opened_at=datetime.fromtimestamp(b.opened_at, timezone.utc),
                             closes_at=datetime.fromtimestamp(b.closes_at, timezone.utc)),
            *(SoundclashCandidate(battle_id=b.battle_id, track_id=c["trackId"], submitted_by_user_id=c["submittedBy"],
                                  vote_count=tally.get(c["trackId"], 0)) for c in b.candidates))
        await self.broadcast("lounge.soundclash.resolved", {"battleId": b.battle_id, "winningTrackId": winner_id,
                                                            "tally": tally, "tieBreak": tie_break})
        await self.push_state("battle")
        winner = catalog.get(winner_id)
        if winner:
            text, sources = rag.battle_banter(winner, tally.get(winner_id, 0), sum(tally.values()))
            await self.announce(text, winner_id, sources, "battle")
        # A pending segue decided before the battle is now stale; re-decide around the winner.
        if self.state.pending_segue:
            self.state.pending_segue = None

    # ---------- lifecycle ----------
    async def start(self):
        if self.state.status == "live":
            return
        self.state.start(self.seed_track_id)
        now = time.time()
        for uid in self.state.connected_ids():
            self.listen_since[uid] = now
        sink.event(self.lounge_id, "loungeStarted", {"seedTrackId": self.seed_track_id})
        sink.event(self.lounge_id, "nowPlaying", {"trackId": self.seed_track_id})
        async with SessionLocal() as s:
            lounge = await s.get(Lounge, self.lounge_id)
            lounge.status, lounge.started_at, lounge.current_track_id = "live", datetime.now(timezone.utc), \
                self.seed_track_id
            await s.commit()
        self.start_loop()
        await self.push_state("start")

    async def end(self):
        from ..analytics import session_analytics

        st = self.state
        if st.now_playing:
            self._record_listens(st.now_playing)
        st.status = "ended"
        st._bump()
        sink.event(self.lounge_id, "loungeEnded", {"peakParticipants": st.peak_participants})
        await sink.flush()
        async with SessionLocal() as s:
            lounge = await s.get(Lounge, self.lounge_id)
            lounge.status, lounge.ended_at = "ended", datetime.now(timezone.utc)
            lounge.current_track_id = st.now_playing["trackId"] if st.now_playing else None
            for item in st.next_up:
                s.add(QueueEntry(id=item.entry_id, lounge_id=self.lounge_id, track_id=item.track_id,
                                 position=item.position, vote_count=len(item.votes), added_by_user_id=item.added_by))
            await s.commit()
            lounge.summary = await session_analytics(s, self.lounge_id)
            await s.commit()
        await self.push_state("ended")
        for ws in list(self.sockets):
            try:
                await ws.close(code=4000)
            except Exception:
                pass
        self.sockets.clear()


class Hub:
    def __init__(self):
        self.runtimes: dict[str, Runtime] = {}

    async def get(self, lounge_id: str) -> Runtime | None:
        rt = self.runtimes.get(lounge_id)
        if rt:
            return rt
        async with SessionLocal() as s:
            lounge = await s.get(Lounge, lounge_id)
        if lounge is None:
            return None
        rt = self.runtimes.setdefault(lounge_id, Runtime(lounge))
        return rt

    def live(self) -> list[Runtime]:
        return [rt for rt in self.runtimes.values() if rt.state.status == "live"]


hub = Hub()

__all__ = ["hub", "Runtime", "QueueError", "sanitize_text", "classify", "EMOJI", "ALLOWED_REACTIONS"]
