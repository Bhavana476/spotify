"""Scripted crowd: N WebSocket clients join one lounge against a RUNNING server and exercise the full demo
path, while measuring the PRD 10.2 numbers (queue sync drift, fan-out, API P95, AI DJ latency).

Usage:  python -m scripts.crowd_sim --base http://localhost:8000 --clients 10 [--out ../docs/perf-results.json]
"""
import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx
import websockets

PASSWORD = "crowd-sim-pass"


def p95(xs):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))], 2) if xs else None


class Client:
    def __init__(self, name, token, user_id):
        self.name, self.token, self.user_id = name, token, user_id
        self.ws = None
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.arrivals: dict[int, float] = {}  # version -> local receive time of a queue.update
        self.queues: dict[int, list] = {}
        self.fanout_ms: list[float] = []

    async def connect(self, ws_base, lounge_id):
        self.ws = await websockets.connect(f"{ws_base}/ws/lounges/{lounge_id}?token={self.token}", max_size=2**22)
        asyncio.create_task(self._reader())

    async def _reader(self):
        try:
            async for raw in self.ws:
                now = time.time()
                msg = json.loads(raw)
                if msg["event"] == "lounge.queue.update":
                    self.arrivals.setdefault(msg["version"], time.perf_counter())
                    self.queues[msg["version"]] = [q["entryId"] for q in msg["payload"]["queue"]]
                    self.fanout_ms.append(now * 1000 - msg["ts"])
                await self.inbox.put(msg)
        except websockets.ConnectionClosed:
            pass

    async def send(self, event, payload=None):
        await self.ws.send(json.dumps({"event": event, "payload": payload or {}, "requestId": uuid.uuid4().hex}))

    async def wait_for(self, event, pred=lambda m: True, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(self.inbox.get(), deadline - time.time())
            except asyncio.TimeoutError:
                break
            if msg["event"] == event and pred(msg):
                return msg
        raise TimeoutError(f"{self.name}: no {event}")


async def make_user(http, i, run_id):
    email = f"crowd{run_id}_{i}@djstudio.dev"
    r = await http.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD,
                                                       "displayName": f"Crowd {i}"})
    r.raise_for_status()
    data = r.json()
    return data["accessToken"], data["user"]["userId"]


async def main(base, n_clients, out):
    ws_base = base.replace("http", "ws", 1)
    run_id = uuid.uuid4().hex[:6]
    report = {"clients": n_clients, "base": base}
    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        users = [await make_user(http, i, run_id) for i in range(n_clients)]
        H = {"Authorization": f"Bearer {users[0][0]}"}

        # ---- API latency (non-AI) ----
        lat = []
        for i in range(100):
            t0 = time.perf_counter()
            r = await http.get("/api/v1/tracks/t_2001/acoustic-profile" if i % 2 else "/api/v1/tracks", headers=H)
            r.raise_for_status()
            lat.append((time.perf_counter() - t0) * 1000)
        report["apiLatencyMs"] = {"p50": round(statistics.median(lat), 2), "p95": p95(lat), "n": len(lat),
                                  "target_p95": 200}

        lounge = (await http.post("/api/v1/lounges", headers=H, json={
            "seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM", "maxParticipants": 50,
            "bpmTolerancePct": 8, "soundclashEnabled": True, "aiVerbosity": "normal"})).json()
        lid = lounge["loungeId"]
        print(f"lounge {lid} invite {lounge['inviteCode']}")

        # ---- AI DJ segue latency (REST, stateless decisions) ----
        ai = []
        for i in range(30):
            t0 = time.perf_counter()
            r = await http.post(f"/api/v1/lounges/{lid}/ai/segue", headers=H, json={
                "currentTrackId": "t_2001", "candidateTrackIds": ["t_2002", "t_2003", "t_2004", "t_3001", "t_5001"],
                "currentSentimentScore": (i % 10) / 10})
            r.raise_for_status()
            ai.append((time.perf_counter() - t0) * 1000)
        report["aiSegueLatencyMs"] = {"p50": round(statistics.median(ai), 2), "p95": p95(ai), "n": len(ai),
                                      "target_p95": 3000, "generator": r.json()["generator"]}
        print("sample segue decision:", json.dumps(r.json(), indent=1)[:600])

    clients = [Client(f"c{i}", tok, uid) for i, (tok, uid) in enumerate(users)]
    host = clients[0]
    for c in clients:
        await c.connect(ws_base, lid)
        await c.wait_for("lounge.sync.state")
    await host.send("playback.start")
    await host.wait_for("lounge.queue.update", lambda m: m["payload"]["reason"] == "start")
    for tid in ("t_2002", "t_2003", "t_2005", "t_2006", "t_3001"):
        await host.send("queue.add", {"trackId": tid})
    snap = await host.wait_for("lounge.queue.update", lambda m: len(m["payload"]["queue"]) == 5)
    entries = [q["entryId"] for q in snap["payload"]["queue"]]

    # ---- Concurrent votes: every client votes at once on different tracks ----
    for c in clients:
        c.arrivals.clear()
    await asyncio.gather(*(c.send("queue.vote", {"entryId": entries[(i * 3) % len(entries)]})
                           for i, c in enumerate(clients)))
    await asyncio.sleep(1.5)
    final_versions = {max(c.queues) for c in clients}
    final_orders = {tuple(c.queues[max(c.queues)]) for c in clients}
    drifts = []
    for version in set.intersection(*(set(c.arrivals) for c in clients)):
        times = [c.arrivals[version] for c in clients]
        drifts.append((max(times) - min(times)) * 1000)
    report["concurrentVotes"] = {"votes": len(clients), "finalVersionsSeen": sorted(final_versions),
                                 "allClientsAgreeOnFinalOrder": len(final_orders) == 1}
    report["queueSyncDriftMs"] = {"p50": round(statistics.median(drifts), 2) if drifts else None,
                                  "p95": p95(drifts), "max": round(max(drifts), 2) if drifts else None,
                                  "updatesMeasured": len(drifts), "target": 100}
    fan = [x for c in clients for x in c.fanout_ms]
    report["fanoutMs"] = {"p95": p95(fan), "max": round(max(fan), 2), "target": 500}

    # ---- Soundclash ----
    await clients[1].send("soundclash.submit", {"trackId": "t_2004"})
    await host.wait_for("lounge.queue.update", lambda m: m["payload"]["submissions"])
    await host.send("soundclash.open")
    opened = await clients[1].wait_for("lounge.soundclash.open")
    cands = opened["payload"]["candidateTrackIds"]
    await asyncio.gather(*(c.send("soundclash.vote", {"trackId": cands[1] if i % 3 else cands[0]})
                           for i, c in enumerate(clients)))
    await asyncio.sleep(0.5)
    await host.send("soundclash.resolve")
    resolved = [await c.wait_for("lounge.soundclash.resolved") for c in clients]
    report["soundclash"] = {"candidates": cands, "winner": resolved[0]["payload"]["winningTrackId"],
                            "tally": resolved[0]["payload"]["tally"],
                            "allClientsSameResult": len({json.dumps(r["payload"]) for r in resolved}) == 1}
    banter = await clients[2].wait_for("lounge.ai.dj_announcement", lambda m: m["payload"]["kind"] == "battle")
    report["soundclash"]["banter"] = banter["payload"]["text"]

    # ---- AI segue in the live room + grounded Q&A ----
    await host.send("playback.seek_outro")
    seg = await clients[3].wait_for("lounge.ai.dj_announcement", lambda m: m["payload"]["kind"] == "segue")
    report["liveSegue"] = seg["payload"]
    await clients[2].send("ai.ask", {"question": "where's this sample from?"})
    ans = await clients[2].wait_for("lounge.chat.message", lambda m: m["payload"]["msgType"] == "ai_answer")
    report["qa"] = {k: ans["payload"][k] for k in ("question", "body", "sourceEvents", "grounded")}

    # ---- Sentiment shift ----
    hype = ["this drop is insane 🔥", "absolute banger!!", "love this so much", "lets goooo", "DJ is killing it"]
    for i, c in enumerate(clients):
        await c.send("chat.send", {"body": hype[i % len(hype)]})
    up = await host.wait_for("lounge.sentiment.score", lambda m: m["payload"]["rollingScore"] > 0.6)
    sad = ["so boring", "skip this 😴", "energy is dead", "ugh not this", "falling asleep"]
    for _ in range(3):
        for i, c in enumerate(clients):
            await c.send("chat.send", {"body": sad[i % len(sad)]})
    t0 = time.time()
    down = await host.wait_for("lounge.sentiment.score", lambda m: m["payload"]["rollingScore"] < 0.45, timeout=15)
    report["sentimentShift"] = {"afterPositiveBurst": up["payload"], "afterNegativeBurst": down["payload"],
                                "secondsToReflect": round(time.time() - t0, 2)}

    # ---- Reconnect: drop and rejoin within the grace window, no duplicate join ----
    await clients[4].ws.close()
    await asyncio.sleep(0.5)
    t0 = time.perf_counter()
    rejoin = Client("c4b", clients[4].token, clients[4].user_id)
    await rejoin.connect(ws_base, lid)
    sync = await rejoin.wait_for("lounge.sync.state")
    report["reconnect"] = {"resyncMs": round((time.perf_counter() - t0) * 1000, 1),
                           "chatHistoryRestored": len(sync["payload"]["chatHistory"])}

    async with httpx.AsyncClient(base_url=base, timeout=30) as http:
        await http.post(f"/api/v1/lounges/{lid}/end", headers={"Authorization": f"Bearer {host.token}"})
        await asyncio.sleep(0.5)
        stats = (await http.get(f"/api/v1/lounges/{lid}/analytics",
                                headers={"Authorization": f"Bearer {host.token}"})).json()
        report["analytics"] = {k: v for k, v in stats.items() if k not in ("lounge", "sentimentTimeline")}
        report["analytics"]["sentimentTimelinePoints"] = len(stats["sentimentTimeline"])
    for c in clients:
        try:
            await c.ws.close()
        except Exception:
            pass
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")  # avoids Windows IPv6 localhost fallback delay
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--out")
    a = ap.parse_args()
    asyncio.run(main(a.base, a.clients, a.out))
