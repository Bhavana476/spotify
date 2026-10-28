"""Generates docs/postman_collection.json (Postman v2.1). Re-run after changing endpoints:
    python docs/make_postman.py
Run the collection top-to-bottom (Collection Runner): each request stores what later ones need."""
import json
from pathlib import Path


def req(name, method, path, body=None, expect=200, token="accessToken", script=(), desc=""):
    item = {
        "name": name,
        "request": {
            "method": method,
            "url": {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"], "path": [p for p in path.split("/") if p]},
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "description": desc,
        },
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": [
            f"pm.test('status is {expect}', () => pm.response.to.have.status({expect}));", *script]}}],
    }
    if token:
        item["request"]["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + token + "}}", "type": "string"}]}
    else:
        item["request"]["auth"] = {"type": "noauth"}
    if body is not None:
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2, ensure_ascii=False),
                                   "options": {"raw": {"language": "json"}}}
    return item


def save(var, expr):
    return f"pm.collectionVariables.set('{var}', {expr});"


login = lambda who, var: req(  # noqa: E731
    f"Log in as {who}", "POST", "/api/v1/auth/login", {"email": f"{who}@djstudio.dev", "password": "{{demoPassword}}"},
    token=None, script=[save(var, "pm.response.json().accessToken"),
                        *( [save("refreshToken", "pm.response.json().refreshToken")] if var == "accessToken" else [])])

TRACK = {"trackId": "t_postman", "title": "Postman Pressing", "artist": "The Collectors", "durationSeconds": 200,
         "acoustic": {"bpm": 124, "camelotKey": "8A", "energy": 0.7, "valence": 0.6},
         "timeline": [{"ts": 10, "type": "trivia", "text": "Filed through the Postman collection."}]}

collection = {
    "info": {"name": "AI DJ Studio — The Listening Room API",
             "description": "Every REST endpoint from docs/API.md. Start the server and seed the DB first. "
                            "WebSocket events are documented in docs/API.md (Postman v2.1 collections cannot hold them; "
                            "use Postman's WebSocket request or `python -m scripts.crowd_sim`).",
             "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "variable": [{"key": k, "value": v} for k, v in {
        "baseUrl": "http://127.0.0.1:8000", "demoPassword": "djstudio-demo", "accessToken": "", "refreshToken": "",
        "adminToken": "", "listenerToken": "", "loungeId": "", "inviteCode": ""}.items()],
    "item": [
        {"name": "0 · Health", "item": [req("API health", "GET", "/health", token=None),
                                        req("Gateway health", "GET", "/health/gateway", token=None)]},
        {"name": "1 · Auth", "item": [
            login("host", "accessToken"),
            req("Who am I", "GET", "/api/v1/auth/me", script=["pm.test('is host', () => pm.expect(pm.response.json().email).to.eql('host@djstudio.dev'));"]),
            req("Refresh (rotates the refresh token)", "POST", "/api/v1/auth/refresh", {"refreshToken": "{{refreshToken}}"},
                token=None, script=[save("accessToken", "pm.response.json().accessToken"),
                                    save("refreshToken", "pm.response.json().refreshToken")]),
            req("Register a new member", "POST", "/api/v1/auth/register",
                {"email": "member{{$timestamp}}@djstudio.dev", "password": "a-long-password", "displayName": "Postman Member"},
                expect=201, token=None),
        ]},
        {"name": "2 · Tracks", "item": [
            req("Catalog", "GET", "/api/v1/tracks", script=["pm.test('25+ tracks', () => pm.expect(pm.response.json().length).to.be.at.least(25));"]),
            req("Acoustic profile (PRD 7.3.2)", "GET", "/api/v1/tracks/t_2001/acoustic-profile",
                script=["pm.test('8A at 124 BPM', () => { const a = pm.response.json().acoustic; pm.expect(a.camelotKey).to.eql('8A'); pm.expect(a.bpm).to.eql(124); });"]),
            req("Rule-valid segues from a track", "GET", "/api/v1/tracks/t_2001/compatible?sentiment=0.7"),
        ]},
        {"name": "3 · Lounges", "item": [
            req("Create lounge (PRD 7.3.1)", "POST", "/api/v1/lounges",
                {"seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM", "maxParticipants": 40, "bpmTolerancePct": 8,
                 "soundclashEnabled": True, "aiVerbosity": "normal"}, expect=201,
                script=[save("loungeId", "pm.response.json().loungeId"), save("inviteCode", "pm.response.json().inviteCode")]),
            req("Open lounges", "GET", "/api/v1/lounges"),
            req("Find by invite code", "GET", "/api/v1/lounges/by-code/{{inviteCode}}"),
            req("Lounge + live state", "GET", "/api/v1/lounges/{{loungeId}}"),
            req("Start the set (host)", "POST", "/api/v1/lounges/{{loungeId}}/start"),
            req("AI segue decision (PRD 7.3.3)", "POST", "/api/v1/lounges/{{loungeId}}/ai/segue",
                {"currentTrackId": "t_2001", "currentTs": 198, "candidateTrackIds": ["t_2002", "t_2003", "t_2004", "t_3001"],
                 "currentSentimentScore": 0.72},
                script=["pm.test('picked a rule-valid segue with reasons', () => { const d = pm.response.json(); pm.expect(d.aiSelected).to.be.true; pm.expect(d.matchReason).to.have.property('camelotRelation'); });"]),
            req("AI segue — no valid candidate", "POST", "/api/v1/lounges/{{loungeId}}/ai/segue",
                {"currentTrackId": "t_2001", "candidateTrackIds": ["t_5004"], "currentSentimentScore": 0.5}, expect=409,
                desc="t_5004 is 82 BPM / 1A: fails both rules, so the DJ refuses rather than bend them."),
            req("Ask the AI DJ (grounded)", "POST", "/api/v1/lounges/{{loungeId}}/ai/ask",
                {"question": "where's this sample from?", "trackId": "t_2001"},
                script=["pm.test('cites the sample credit', () => pm.expect(pm.response.json().sourceEvents).to.include('evt_2001_1'));"]),
            req("Ask the AI DJ (declines without notes)", "POST", "/api/v1/lounges/{{loungeId}}/ai/ask",
                {"question": "what was its chart position in Japan?", "trackId": "t_2001"},
                script=["pm.test('not grounded, no sources', () => { const r = pm.response.json(); pm.expect(r.grounded).to.be.false; pm.expect(r.sourceEvents).to.eql([]); });"]),
            req("Chat history", "GET", "/api/v1/lounges/{{loungeId}}/chat?limit=50"),
            req("End the night (host)", "POST", "/api/v1/lounges/{{loungeId}}/end"),
            req("Ledger / analytics", "GET", "/api/v1/lounges/{{loungeId}}/analytics",
                script=["pm.test('has a sentiment timeline and battles list', () => { const a = pm.response.json(); pm.expect(a).to.have.property('sentimentTimeline'); pm.expect(a).to.have.property('battles'); });"]),
        ]},
        {"name": "4 · Dashboard", "item": [
            req("Dashboard", "GET", "/api/v1/me/dashboard"),
            req("Recommendations", "GET", "/api/v1/me/recommendations?k=5",
                script=["pm.test('5 ranked picks', () => pm.expect(pm.response.json().items.length).to.eql(5));"]),
        ]},
        {"name": "5 · Admin & RBAC", "item": [
            login("admin", "adminToken"),
            login("listener", "listenerToken"),
            req("Listener tries an admin upload → 403", "PUT", "/api/v1/admin/tracks", TRACK, expect=403, token="listenerToken"),
            req("Listener tries to start someone's lounge → 403", "POST", "/api/v1/lounges/{{loungeId}}/start",
                expect=403, token="listenerToken"),
            req("Validate: bad Camelot key → 422", "POST", "/api/v1/admin/tracks/validate",
                {**TRACK, "acoustic": {**TRACK["acoustic"], "camelotKey": "13C"}}, expect=422, token="adminToken",
                script=["pm.test('names the field', () => pm.expect(pm.response.json().errors[0].field).to.eql('acoustic.camelotKey'));"]),
            req("Upload a track profile", "PUT", "/api/v1/admin/tracks", TRACK, expect=201, token="adminToken"),
            req("List users", "GET", "/api/v1/admin/users", token="adminToken"),
            req("Retrain recommender", "POST", "/api/v1/admin/recommender/retrain", token="adminToken"),
            req("Delete the uploaded track", "DELETE", "/api/v1/admin/tracks/t_postman", expect=204, token="adminToken"),
        ]},
        {"name": "6 · Sign out", "item": [
            req("Log out (revokes refresh token)", "POST", "/api/v1/auth/logout", {"refreshToken": "{{refreshToken}}"},
                expect=204, token=None),
            req("Revoked refresh token is refused", "POST", "/api/v1/auth/refresh", {"refreshToken": "{{refreshToken}}"},
                expect=401, token=None),
        ]},
    ],
}

out = Path(__file__).with_name("postman_collection.json")
out.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out} with {sum(len(f['item']) for f in collection['item'])} requests")
