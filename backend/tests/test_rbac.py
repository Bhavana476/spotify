"""Server-side RBAC across all four roles, over HTTP and over the WebSocket gateway."""
import pytest

from .conftest import auth
from .test_integration import new_lounge, recv_until

UPLOAD = {"trackId": "t_rbac", "title": "RBAC Test", "artist": "QA", "durationSeconds": 120,
          "acoustic": {"bpm": 124, "camelotKey": "8A", "energy": 0.5, "valence": 0.5}, "timeline": []}


def test_unauthenticated_is_rejected(client):
    assert client.get("/api/v1/tracks").status_code == 401
    assert client.get("/api/v1/tracks", headers={"Authorization": "Bearer garbage"}).status_code == 401


@pytest.mark.parametrize("who,code", [("listener", 403), ("codj", 403), ("host", 403), ("admin", 201)])
def test_acoustic_upload_is_admin_only(client, tokens, who, code):
    assert client.put("/api/v1/admin/tracks", json=UPLOAD, headers=auth(tokens[who])).status_code == code


def test_admin_user_management_admin_only(client, tokens):
    assert client.get("/api/v1/admin/users", headers=auth(tokens["listener"])).status_code == 403
    assert client.get("/api/v1/admin/users", headers=auth(tokens["admin"])).status_code == 200


def test_lounge_scoped_roles_over_http(client, tokens):
    lounge = new_lounge(client, tokens["host"])
    lid = lounge["loungeId"]
    body = {"currentTrackId": "t_2001", "candidateTrackIds": ["t_2002", "t_2003"], "currentSentimentScore": 0.7}
    # listener: rejected; host & admin: allowed
    assert client.post(f"/api/v1/lounges/{lid}/ai/segue", json=body,
                       headers=auth(tokens["listener"])).status_code == 403
    assert client.post(f"/api/v1/lounges/{lid}/ai/segue", json=body, headers=auth(tokens["host"])).status_code == 200
    assert client.post(f"/api/v1/lounges/{lid}/ai/segue", json=body,
                       headers=auth(tokens["admin"])).status_code == 200
    # only the host (or admin) can start/end it
    assert client.post(f"/api/v1/lounges/{lid}/start", headers=auth(tokens["listener"])).status_code == 403
    assert client.post(f"/api/v1/lounges/{lid}/end", headers=auth(tokens["codj"])).status_code == 403


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws/lounges/lg_nope?token=bad") as ws:
            ws.receive_json()
    assert e.value.code == 4401


def test_websocket_role_enforcement_all_four_roles(client, tokens):
    lounge = new_lounge(client, tokens["host"])
    lid = lounge["loungeId"]
    url = f"/ws/lounges/{lid}?token="
    with client.websocket_connect(url + tokens["host"]["accessToken"]) as host, \
            client.websocket_connect(url + tokens["codj"]["accessToken"]) as codj, \
            client.websocket_connect(url + tokens["listener"]["accessToken"]) as listener:
        for ws in (host, codj, listener):
            recv_until(ws, "lounge.sync.state")
        # Listener tries host/co-DJ actions -> rejected server-side.
        for event in ("playback.start", "soundclash.open", "soundclash.resolve", "ai.segue.request", "mod.lock"):
            listener.send_json({"event": event, "payload": {}, "requestId": event})
            err = recv_until(listener, "lounge.error")
            assert err["payload"]["code"] == "forbidden", event
        # Host promotes codj to Co-DJ; Co-DJ may then open the AI segue flow but still not host-only actions.
        codj_id = tokens["codj"]["user"]["userId"]
        host.send_json({"event": "playback.start", "payload": {}, "requestId": "s"})
        recv_until(host, "lounge.ack")
        host.send_json({"event": "mod.set_role", "payload": {"userId": codj_id, "role": "co_dj"}, "requestId": "r"})
        recv_until(host, "lounge.ack")
        codj.send_json({"event": "ai.segue.request", "payload": {}, "requestId": "seg"})
        recv_until(codj, "lounge.ack")
        codj.send_json({"event": "mod.lock", "payload": {}, "requestId": "lock"})
        assert recv_until(codj, "lounge.error")["payload"]["code"] == "forbidden"
    # Admin is allowed host-level actions in any lounge.
    with client.websocket_connect(url + tokens["admin"]["accessToken"]) as admin:
        recv_until(admin, "lounge.sync.state")
        admin.send_json({"event": "mod.lock", "payload": {"locked": False}, "requestId": "a"})
        recv_until(admin, "lounge.ack")
