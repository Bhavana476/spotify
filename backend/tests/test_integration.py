"""End-to-end over the real HTTP API + WebSocket gateway (TestClient, SQLite)."""
import time

from .conftest import auth


def new_lounge(client, host_tok, **overrides) -> dict:
    body = {"seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM", "maxParticipants": 40,
            "bpmTolerancePct": 8, "soundclashEnabled": True, "aiVerbosity": "normal", **overrides}
    r = client.post("/api/v1/lounges", json=body, headers=auth(host_tok))
    assert r.status_code == 201, r.text
    return r.json()


def recv_until(ws, event: str, pred=lambda m: True, limit: int = 300) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["event"] == event and pred(msg):
            return msg
    raise AssertionError(f"never received {event}")


def ws_url(lounge_id, tok):
    return f"/ws/lounges/{lounge_id}?token={tok['accessToken']}"


def test_health(client):
    assert client.get("/health").json()["tracks"] >= 24
    assert client.get("/health/gateway").json()["status"] == "ok"


def test_create_lounge_contract(client, tokens):
    data = new_lounge(client, tokens["host"])
    assert set(data) == {"loungeId", "inviteCode", "status", "hostUserId", "createdAt"}
    assert data["status"] == "scheduled" and data["inviteCode"].startswith("SP-")
    found = client.get(f"/api/v1/lounges/by-code/{data['inviteCode'].lower()}", headers=auth(tokens["guest"]))
    assert found.json()["loungeId"] == data["loungeId"]


def test_acoustic_profile_contract(client, tokens):
    data = client.get("/api/v1/tracks/t_2001/acoustic-profile", headers=auth(tokens["listener"])).json()
    assert data["acoustic"] == {"bpm": 124, "camelotKey": "8A", "energy": 0.78, "valence": 0.65}
    assert data["timeline"][0]["type"] == "sample_credit"
    assert client.get("/api/v1/tracks/nope/acoustic-profile", headers=auth(tokens["listener"])).status_code == 404


def test_acoustic_upload_validation(client, tokens):
    base = {"title": "X", "artist": "Y", "durationSeconds": 200, "timeline": []}
    cases = [({"bpm": -5, "camelotKey": "8A", "energy": 0.5, "valence": 0.5}, "acoustic.bpm"),
             ({"bpm": 120, "camelotKey": "13C", "energy": 0.5, "valence": 0.5}, "acoustic.camelotKey"),
             ({"bpm": 120, "camelotKey": "8A", "energy": 1.5, "valence": 0.5}, "acoustic.energy"),
             ({"bpm": 120, "camelotKey": "8A", "energy": 0.5, "valence": -0.1}, "acoustic.valence")]
    for acoustic, field in cases:
        r = client.post("/api/v1/admin/tracks/validate", json={**base, "acoustic": acoustic},
                        headers=auth(tokens["admin"]))
        assert r.status_code == 422
        assert r.json()["errors"][0]["field"] == field
    r = client.post("/api/v1/admin/tracks/validate", json={**base, "acoustic": {
        "bpm": 120, "camelotKey": "8A", "energy": 0.5, "valence": 0.5}}, headers=auth(tokens["admin"]))
    assert "13C" not in r.text and r.json()["valid"] is True
    bad = client.post("/api/v1/admin/tracks/validate", json={**base, "acoustic": {
        "bpm": 120, "camelotKey": "13C", "energy": 0.5, "valence": 0.5}}, headers=auth(tokens["admin"]))
    assert "not a valid Camelot key" in bad.json()["errors"][0]["message"]


def test_refresh_token_rotation(client, tokens):
    from .conftest import login
    tok = login(client, "guest@djstudio.dev")
    r1 = client.post("/api/v1/auth/refresh", json={"refreshToken": tok["refreshToken"]})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/refresh", json={"refreshToken": tok["refreshToken"]})
    assert r2.status_code == 401  # single use


def test_live_room_queue_sync_battle_ai_and_analytics(client, tokens):
    lounge = new_lounge(client, tokens["host"])
    lid = lounge["loungeId"]
    with client.websocket_connect(ws_url(lid, tokens["host"])) as host, \
            client.websocket_connect(ws_url(lid, tokens["listener"])) as listener:
        recv_until(host, "lounge.sync.state")
        recv_until(listener, "lounge.sync.state")
        host.send_json({"event": "playback.start", "payload": {}})
        state = recv_until(listener, "lounge.queue.update", lambda m: m["payload"]["reason"] == "start")
        assert state["payload"]["nowPlaying"]["trackId"] == "t_2001"

        for tid in ("t_2002", "t_2003", "t_2005"):
            host.send_json({"event": "queue.add", "payload": {"trackId": tid}, "requestId": tid})
            recv_until(host, "lounge.ack")

        # Vote-driven reorder: both clients see the identical order at the identical version.
        snap = recv_until(listener, "lounge.queue.update",
                          lambda m: len(m["payload"]["queue"]) == 3)["payload"]["queue"]
        target = snap[2]["entryId"]
        listener.send_json({"event": "queue.vote", "payload": {"entryId": target}})
        a = recv_until(listener, "lounge.queue.update", lambda m: m["payload"]["reason"] == "vote")
        b = recv_until(host, "lounge.queue.update", lambda m: m["payload"]["reason"] == "vote")
        assert a["version"] == b["version"]
        assert a["payload"]["queue"] == b["payload"]["queue"]
        assert a["payload"]["queue"][0]["entryId"] == target

        # Mid-session join receives the full current state within 2 s.
        t0 = time.perf_counter()
        with client.websocket_connect(ws_url(lid, tokens["guest"])) as guest:
            sync = recv_until(guest, "lounge.sync.state")
            assert time.perf_counter() - t0 < 2
            assert sync["payload"]["nowPlaying"]["trackId"] == "t_2001"
            assert [q["entryId"] for q in sync["payload"]["queue"]] == [q["entryId"] for q in a["payload"]["queue"]]

        # Soundclash: submit -> open -> vote -> resolve -> winner spliced into Next Up on every client.
        listener.send_json({"event": "soundclash.submit", "payload": {"trackId": "t_2004"}, "requestId": "sub"})
        recv_until(listener, "lounge.ack")
        host.send_json({"event": "soundclash.open", "payload": {}})
        opened = recv_until(listener, "lounge.soundclash.open")
        assert "t_2004" in opened["payload"]["candidateTrackIds"]
        listener.send_json({"event": "soundclash.vote", "payload": {"trackId": "t_2004"}, "requestId": "v1"})
        recv_until(listener, "lounge.ack")
        host.send_json({"event": "soundclash.vote", "payload": {"trackId": "t_2004"}, "requestId": "v2"})
        recv_until(host, "lounge.ack")
        host.send_json({"event": "soundclash.resolve", "payload": {}})
        r_l = recv_until(listener, "lounge.soundclash.resolved")
        r_h = recv_until(host, "lounge.soundclash.resolved")
        assert r_l["payload"] == r_h["payload"] and r_l["payload"]["winningTrackId"] == "t_2004"
        q = recv_until(listener, "lounge.queue.update", lambda m: m["payload"]["reason"] == "battle"
                       and m["payload"]["lastBattle"] is not None)
        assert q["payload"]["queue"][0]["trackId"] == "t_2004" and q["payload"]["queue"][0]["locked"] == "battle"

        # AI segue on demand: the battle winner (8B from 8A @124->128) is rule-valid, so it is AI-confirmed.
        host.send_json({"event": "ai.segue.request", "payload": {}})
        ann = recv_until(listener, "lounge.ai.dj_announcement", lambda m: m["payload"]["kind"] == "segue")
        assert ann["payload"]["relatedTrackId"] == "t_2004" and ann["payload"]["sourceEvents"]

        # Grounded Q&A.
        listener.send_json({"event": "ai.ask", "payload": {"question": "where's this sample from?"}})
        ans = recv_until(listener, "lounge.chat.message", lambda m: m["payload"]["msgType"] == "ai_answer")
        assert ans["payload"]["grounded"] and ans["payload"]["sourceEvents"] == ["evt_2001_1"]

        # Sentiment visibly drops after a negative burst, within one aggregation tick.
        for _ in range(6):
            listener.send_json({"event": "chat.send", "payload": {"body": "so boring, skip this 😴"}})
        tick = recv_until(listener, "lounge.sentiment.score", lambda m: m["payload"]["rollingScore"] < 0.35)
        assert tick["payload"]["sampleSize"] >= 6

        # XSS in chat is neutralised before storage / fan-out.
        listener.send_json({"event": "chat.send", "payload": {"body": "it's <script>alert(1)</script><img src=x "
                                                                       "onerror=alert(2)>ok"}})
        msg = recv_until(listener, "lounge.chat.message", lambda m: "alert" in m["payload"]["body"])
        assert msg["payload"]["body"] == "it's alert(1)ok"

        host.send_json({"event": "lounge.end", "payload": {}})
        recv_until(listener, "lounge.queue.update", lambda m: m["payload"]["reason"] == "ended")

    # Analytics reconcile exactly with the raw event log.
    stats = client.get(f"/api/v1/lounges/{lid}/analytics", headers=auth(tokens["host"])).json()
    assert stats["soundclashBattles"] == 1 and stats["aiQuestionsAsked"] == 1
    # The battle is also persisted to soundclash_battles / soundclash_candidates and agrees with the event log.
    assert len(stats["battles"]) == 1
    battle = stats["battles"][0]
    assert battle["winningTrackId"] == "t_2004" and battle["candidates"][0] == {
        "trackId": "t_2004", "votes": 2, "submittedBy": tokens["listener"]["user"]["userId"]}
    assert stats["peakConcurrentParticipants"] == 3
    assert stats["chatMessages"] == 7 and stats["votes"] == 1
    assert stats["sentimentTimeline"] and stats["sentimentTimeline"][-1]["score"] < 0.35
    assert client.get(f"/api/v1/lounges/{lid}/analytics",
                      headers=auth(tokens["codj"])).status_code == 403  # never joined


def test_host_disconnect_freezes_queue(client, tokens):
    lid = new_lounge(client, tokens["host"])["loungeId"]
    with client.websocket_connect(ws_url(lid, tokens["listener"])) as listener:
        recv_until(listener, "lounge.sync.state")
        with client.websocket_connect(ws_url(lid, tokens["host"])) as host:
            recv_until(host, "lounge.sync.state")
            host.send_json({"event": "queue.add", "payload": {"trackId": "t_2002"}, "requestId": "x"})
            recv_until(host, "lounge.ack")
        frozen = recv_until(listener, "lounge.queue.update", lambda m: m["payload"]["frozen"])
        assert frozen["payload"]["hostState"] == "disconnected"
        listener.send_json({"event": "queue.vote", "payload": {"entryId": frozen["payload"]["queue"][0]["entryId"]}})
        assert recv_until(listener, "lounge.error")["payload"]["code"] == "frozen"


def test_dashboard_and_recommendations(client, tokens):
    data = client.get("/api/v1/me/dashboard", headers=auth(tokens["listener"])).json()
    assert data["tasteProfile"] and len(data["recommendations"]) > 0
    recs = client.get("/api/v1/me/recommendations?k=5", headers=auth(tokens["listener"])).json()
    assert len(recs["items"]) == 5 and recs["model"]["interactions"] > 0
