"""WebSocket entry point. Client -> server messages: {"event": "<name>", "payload": {...}, "requestId": "..."}.
The JWT is validated at handshake and its expiry re-checked on every role-sensitive action."""
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from .. import catalog
from ..db import SessionLocal
from ..engine import rag
from ..engine.sentiment import EMOJI, classify
from ..events import sink
from ..models import User
from ..security import decode_token, sanitize_text
from .hub import ALLOWED_REACTIONS, Runtime, hub
from .lounge_state import QueueError

router = APIRouter()
log = logging.getLogger("djstudio.ws")

# Minimum lounge role per action; anything absent here is open to every participant.
SENSITIVE = {
    "queue.promote": "co_dj", "queue.remove": "co_dj", "soundclash.open": "co_dj", "soundclash.resolve": "co_dj",
    "ai.segue.approve": "co_dj", "ai.segue.reject": "co_dj", "ai.segue.request": "co_dj",
    "playback.start": "host", "playback.skip": "co_dj", "playback.seek_outro": "co_dj",
    "mod.mute": "host", "mod.unmute": "host", "mod.remove": "host", "mod.lock": "host",
    "mod.set_role": "host", "mod.transfer_host": "host", "lounge.end": "host", "settings.update": "host",
}


class Ctx:
    def __init__(self, rt: Runtime, ws: WebSocket, user: User):
        self.rt, self.ws, self.user = rt, ws, user
        self.st = rt.state


def _track_or_error(track_id) -> str:
    if not isinstance(track_id, str) or catalog.get(track_id) is None:
        raise QueueError("invalid", "Unknown track")
    return track_id


async def h_chat(c: Ctx, p: dict):
    if c.st.participants[c.user.id].muted:
        raise QueueError("muted", "You are muted by the host")
    body = sanitize_text(str(p.get("body", "")), 500)
    if not body:
        raise QueueError("invalid", "Empty message")
    bucket_name, score = classify(body)
    c.rt.sentiment.add(score)
    msg = {"messageId": f"msg_{uuid.uuid4().hex[:10]}", "userId": c.user.id, "displayName": c.user.display_name,
           "body": body, "msgType": "chat", "sentimentBucket": bucket_name, "sentimentScore": round(score, 3),
           "tsSeconds": time.time()}
    c.rt.chat_log.append(msg)
    sink.chat(msg["messageId"], c.st.lounge_id, c.user.id, "chat", body, score, msg["tsSeconds"])
    sink.event(c.st.lounge_id, "chat", {"messageId": msg["messageId"], "bucket": bucket_name, "score": score},
               c.user.id)
    await c.rt.broadcast("lounge.chat.message", msg)


async def h_typing(c: Ctx, p: dict):
    await c.rt.broadcast("lounge.chat.typing", {"userId": c.user.id, "displayName": c.user.display_name,
                                                "typing": bool(p.get("typing", True))})


async def h_react(c: Ctx, p: dict):
    emoji = p.get("emoji")
    if emoji not in ALLOWED_REACTIONS:
        raise QueueError("invalid", "Unsupported reaction")
    c.rt.sentiment.add(EMOJI.get(emoji, 0) / 3 * 0.5)
    if emoji in ("🔥", "❤️", "💯", "🙌") and c.st.now_playing:
        c.rt.liked_current.add(c.user.id)
    await c.rt.broadcast("lounge.chat.reaction", {"messageId": p.get("messageId"), "emoji": emoji,
                                                  "userId": c.user.id})


async def h_like(c: Ctx, p: dict):
    c.rt.liked_current.add(c.user.id)
    sink.event(c.st.lounge_id, "like", {"trackId": c.st.now_playing and c.st.now_playing["trackId"]}, c.user.id)


async def h_add(c: Ctx, p: dict):
    item = c.st.add_track(_track_or_error(p.get("trackId")), c.user.id)
    sink.event(c.st.lounge_id, "queueAdd", {"trackId": item.track_id, "entryId": item.entry_id}, c.user.id)
    await c.rt.push_state("add")


async def h_vote(c: Ctx, p: dict):
    up = p.get("up", True) is not False
    changed = c.st.vote(c.user.id, str(p.get("entryId")), up)
    sink.event(c.st.lounge_id, "vote", {"entryId": p.get("entryId"), "up": up, "reordered": changed}, c.user.id)
    await c.rt.push_state("vote")


async def h_promote(c: Ctx, p: dict):
    item = c.st.promote(str(p.get("entryId")), "host")
    c.st.pending_segue = None  # re-evaluate the transition around the human choice
    sink.event(c.st.lounge_id, "override", {"entryId": item.entry_id, "trackId": item.track_id}, c.user.id)
    await c.rt.push_state("override")


async def h_remove(c: Ctx, p: dict):
    c.st.remove(str(p.get("entryId")))
    sink.event(c.st.lounge_id, "override", {"removed": p.get("entryId")}, c.user.id)
    await c.rt.push_state("override")


async def h_submit(c: Ctx, p: dict):
    sub = c.st.submit_challenger(_track_or_error(p.get("trackId")), c.user.id)
    sink.event(c.st.lounge_id, "battleSubmit", sub, c.user.id)
    await c.rt.push_state("battle")


async def h_battle_open(c: Ctx, p: dict):
    await c.rt.open_battle(f"user:{c.user.id}")


async def h_battle_vote(c: Ctx, p: dict):
    c.st.battle_vote(c.user.id, str(p.get("trackId")))
    sink.event(c.st.lounge_id, "battleVote", {"battleId": c.st.battle.battle_id, "trackId": p.get("trackId")},
               c.user.id)
    await c.rt.push_state("battle")


async def h_battle_resolve(c: Ctx, p: dict):
    b = c.st.battle
    if not b or b.status == "resolved":
        raise QueueError("no_battle", "No Soundclash to resolve")
    track_id = p.get("trackId")
    if b.status == "open" and not track_id:
        winner = c.st.close_battle()  # force-close now and tally
        await (c.rt._battle_resolved(winner) if winner else c.rt._battle_tied())
        return
    if not track_id:
        raise QueueError("invalid", "Pick one of the tied tracks")
    if b.status == "open":
        b.status = "tied" if len(c.st.tied_track_ids()) > 1 else b.status
        if b.status == "open":
            raise QueueError("invalid", "Battle has a clear leader — resolve without picking a track")
    await c.rt._battle_resolved(c.st.apply_battle_winner(str(track_id)), tie_break="host")


async def h_segue_request(c: Ctx, p: dict):
    c.st.pending_segue = None
    await c.rt.run_segue("manual")


async def h_segue_approve(c: Ctx, p: dict):
    if c.st.pending_segue:
        c.st.pending_segue["status"] = "approved"
        sink.event(c.st.lounge_id, "segueApproved", {"trackId": c.st.pending_segue.get("selectedTrackId")},
                   c.user.id)
        await c.rt.push_state("segue")


async def h_segue_reject(c: Ctx, p: dict):
    pending = c.st.pending_segue
    if not pending or not pending.get("selectedTrackId"):
        raise QueueError("invalid", "No AI segue to reject")
    rejected = pending["selectedTrackId"]
    c.st.rejected_segues.add(rejected)
    for q in c.st.next_up:
        if q.track_id == rejected and q.locked_reason == "segue":
            q.locked_reason = None
    c.st._sort()
    c.st.pending_segue = None
    sink.event(c.st.lounge_id, "segueRejected", {"trackId": rejected}, c.user.id)
    await c.rt.run_segue("host_reject")


async def h_ask(c: Ctx, p: dict):
    question = sanitize_text(str(p.get("question", "")), 300)
    if not question:
        raise QueueError("invalid", "Ask a question")
    track_id = p.get("trackId") or (c.st.now_playing or {}).get("trackId")
    allowed = set(c.st.history[-5:]) | {(c.st.now_playing or {}).get("trackId")}
    if track_id not in allowed:
        raise QueueError("invalid", "You can ask about the current or recently played tracks")
    track = catalog.get(track_id)
    started = time.perf_counter()
    result = await rag.answer_question(question, track)
    result["latencyMs"] = round((time.perf_counter() - started) * 1000, 1)
    sink.event(c.st.lounge_id, "aiQuestion", {"question": question, **result}, c.user.id)
    await c.rt.system_message(result["answer"], "ai_answer", {
        "question": question, "askedBy": c.user.display_name, "sourceEvents": result["sourceEvents"],
        "grounded": result["grounded"], "relatedTrackId": track.id,
        "sources": [e for e in track.timeline if e["id"] in result["sourceEvents"]]})


async def h_start(c: Ctx, p: dict):
    await c.rt.start()


async def h_skip(c: Ctx, p: dict):
    await c.rt.advance_track()


async def h_seek_outro(c: Ctx, p: dict):
    """Demo helper: jump to just before the outro window so the AI DJ segue fires now."""
    from .. import config
    np = c.st.now_playing
    track = catalog.get(np["trackId"]) if np else None
    if not track:
        raise QueueError("invalid", "Nothing playing")
    target_elapsed = track.duration_seconds - config.OUTRO_WINDOW_SECONDS - 1
    np["startedAt"] = time.time() - target_elapsed / config.PLAYBACK_SPEED
    c.st._bump()
    await c.rt.push_state("seek")


def _target(c: Ctx, p: dict) -> int:
    uid = p.get("userId")
    if not isinstance(uid, int) or uid not in c.st.participants:
        raise QueueError("invalid", "Unknown participant")
    if uid == c.st.host_user_id:
        raise QueueError("invalid", "Cannot moderate the host")
    return uid


async def h_mute(c: Ctx, p: dict, muted=True):
    uid = _target(c, p)
    c.st.participants[uid].muted = muted
    sink.event(c.st.lounge_id, "moderation", {"action": "mute" if muted else "unmute", "target": uid}, c.user.id)
    await c.rt.push_state("moderation")


async def h_remove_user(c: Ctx, p: dict):
    uid = _target(c, p)
    c.st.banned.add(uid)
    c.st.co_djs.discard(uid)
    for ws, owner in list(c.rt.sockets.items()):
        if owner == uid:
            await ws.send_json({"event": "lounge.removed", "loungeId": c.st.lounge_id, "payload": {}, "ts": 0})
            await ws.close(code=4403)
    sink.event(c.st.lounge_id, "moderation", {"action": "remove", "target": uid}, c.user.id)
    await c.rt.push_state("moderation")


async def h_lock(c: Ctx, p: dict):
    c.st.locked = bool(p.get("locked", True))
    c.st._bump()
    await c.rt.push_state("moderation")


async def h_set_role(c: Ctx, p: dict):
    uid = _target(c, p)
    role = p.get("role")
    if role == "co_dj":
        c.st.co_djs.add(uid)
    elif role == "listener":
        c.st.co_djs.discard(uid)
    else:
        raise QueueError("invalid", "role must be co_dj or listener")
    c.st._bump()
    sink.event(c.st.lounge_id, "moderation", {"action": "set_role", "target": uid, "role": role}, c.user.id)
    await c.rt.push_state("moderation")


async def h_transfer(c: Ctx, p: dict):
    uid = _target(c, p)
    old = c.st.host_user_id
    c.st.host_user_id = uid
    c.st.co_djs.discard(uid)
    c.st.co_djs.add(old)
    c.st._bump()
    sink.event(c.st.lounge_id, "moderation", {"action": "transfer_host", "target": uid}, c.user.id)
    await c.rt.system_message("Host role transferred.")
    await c.rt.push_state("host")


async def h_end(c: Ctx, p: dict):
    await c.rt.end()


async def h_ping(c: Ctx, p: dict):
    rtt = p.get("lastRttMs")
    if isinstance(rtt, (int, float)):
        c.st.participants[c.user.id].rtt_ms = round(float(rtt), 1)
    await c.ws.send_json({"event": "lounge.sync.pong", "loungeId": c.st.lounge_id,
                          "payload": {"clientSentAt": p.get("clientSentAt"), "serverReceivedAt": time.time() * 1000},
                          "ts": int(time.time() * 1000)})


async def h_renew(c: Ctx, p: dict):
    claims = decode_token(str(p.get("token", "")))
    if int(claims["sub"]) != c.user.id:
        raise QueueError("forbidden", "Token belongs to a different user")
    c.rt.token_exp[c.ws] = claims["exp"]


HANDLERS = {
    "chat.send": h_chat, "chat.typing": h_typing, "chat.react": h_react, "track.like": h_like,
    "queue.add": h_add, "queue.vote": h_vote, "queue.promote": h_promote, "queue.remove": h_remove,
    "soundclash.submit": h_submit, "soundclash.open": h_battle_open, "soundclash.vote": h_battle_vote,
    "soundclash.resolve": h_battle_resolve, "ai.ask": h_ask, "ai.segue.request": h_segue_request,
    "ai.segue.approve": h_segue_approve, "ai.segue.reject": h_segue_reject, "playback.start": h_start,
    "playback.skip": h_skip, "playback.seek_outro": h_seek_outro, "mod.mute": h_mute,
    "mod.unmute": lambda c, p: h_mute(c, p, False), "mod.remove": h_remove_user, "mod.lock": h_lock,
    "mod.set_role": h_set_role, "mod.transfer_host": h_transfer, "lounge.end": h_end, "sync.ping": h_ping,
    "auth.renew": h_renew,
}


@router.websocket("/ws/lounges/{lounge_id}")
async def lounge_socket(websocket: WebSocket, lounge_id: str, token: str = Query(...)):
    try:
        claims = decode_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return
    async with SessionLocal() as s:
        user = await s.get(User, int(claims["sub"]))
    rt = await hub.get(lounge_id)
    if user is None or rt is None:
        await websocket.close(code=4404)
        return
    if rt.state.status == "ended":
        await websocket.close(code=4410)
        return
    await websocket.accept()
    try:
        await rt.on_connect(websocket, user.id, user.display_name, user.role, claims["exp"])
    except QueueError as err:
        await websocket.send_json({"event": "lounge.error", "loungeId": lounge_id,
                                   "payload": {"code": err.code, "message": err.message}, "ts": 0})
        await websocket.close(code=4403)
        return
    ctx = Ctx(rt, websocket, user)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                msg = None
            if not isinstance(msg, dict):
                msg = {}
            event = msg.get("event")
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
            request_id = msg.get("requestId")
            handler = HANDLERS.get(event)
            try:
                if handler is None:
                    raise QueueError("unknown_event", f"Unknown event '{event}'")
                if event in SENSITIVE:
                    if rt.token_exp.get(websocket, 0) < time.time():
                        raise QueueError("token_expired", "Session token expired — renew it")
                    rt.state.require(user.id, user.role, SENSITIVE[event])
                await handler(ctx, payload)
                if request_id:
                    await websocket.send_json({"event": "lounge.ack", "loungeId": lounge_id,
                                               "payload": {"requestId": request_id}, "ts": int(time.time() * 1000)})
            except (QueueError, HTTPException) as err:
                if isinstance(err, HTTPException):
                    err = QueueError("unauthorized", str(err.detail))
                log.info("rejected", extra={"loungeId": lounge_id, "event": event, "code": err.code})
                await websocket.send_json({"event": "lounge.error", "loungeId": lounge_id,
                                           "payload": {"code": err.code, "message": err.message,
                                                       "requestId": request_id, "forEvent": event},
                                           "ts": int(time.time() * 1000)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await rt.on_disconnect(websocket)
