# Architecture (as built)

```
React client (Vite)  ──REST──▶  FastAPI routers: auth · tracks · lounges · me (dashboard) · admin
        │                                │
        └──WebSocket /ws/lounges/{id}──▶ Queue & State Gateway (app/gateway)
                                           ├─ hub.Runtime (one per lounge): sockets, playback clock, ticker
                                           └─ lounge_state.LoungeState: pure, synchronous state machine
                                         │
                                AI DJ Engine (app/engine) — no socket/DB code
                                  acoustic.py   BPM + Camelot hard rules, 50/30/20 ranking
                                  sentiment.py  lexicon scorer + RollingSentiment window
                                  rag.py        retrieval over track timelines, grounded generation
                                  dj.py         segue decision, Soundclash tie-break
                                  recommender.py hybrid content + item-item CF
                                         │
                Persistence: SQLAlchemy async (SQLite default / PostgreSQL via asyncpg)
                  events.EventSink batches queue_events, chat_messages, interactions (1 s / 50 rows)
```

Both entry points run in one process, but they are separate modules. The engine is called from both the
REST routers and the gateway, so the matching and scoring logic exists in exactly one place.
Many lounges run at once: `Hub.runtimes` is keyed by `loungeId`, and nothing assumes a single room.

## Key design decisions
- **Queue state lives in memory (PRD 9.4).** `LoungeState` mutations are synchronous. Each one finishes inside a
  single event-loop step and then bumps a `version` counter. Every broadcast carries the *full* snapshot plus its
  version, and clients discard anything older. Together these mean no client ever sees a partial reorder, and
  concurrent votes converge. The concurrent-vote test and the 10-client run both check this.
- **Ordering:** a pinned slot comes first (segue, battle winner or host pick). Everything else is sorted by vote
  count descending, then by sparse `position` (steps of 1000). Promoting an entry changes only that row's
  position, as `test_sparse_positions_only_moved_row_changes` checks.
- **Hard constraints are enforced in code.** `rank_segues` drops every candidate that fails a rule before ranking,
  so an invalid track can never be ranked. When a *human* choice holds Next Up (a host promote or a Soundclash win)
  and it breaks the rules, it is still played, but flagged `aiSelected: false`. It is never passed off as an AI pick.
- **Host-disconnect policy (deterministic):** after a 10 s reconnect grace window, the longest-present connected
  Co-DJ is promoted to host. If there is no Co-DJ, the room enters `hostState: disconnected`, `frozen: true`. Votes,
  adds and battles are rejected until the host returns. The playback clock keeps running.
- **Restarts:** because live queue state is in memory, a server restart orphans any lounge marked `live`. At
  startup `recovery.close_orphaned_lounges()` closes those lounges, writing their summary from the event log
  (`closedBy: "server_restart"`). It also closes scheduled lounges that were never started within 12 hours.
  This stops "ghost booths" from appearing in the open-lounge list.
- **Reconnects:** presence is counted per user across sockets. A drop followed by a rejoin within the grace window
  produces no leave or join events. The new socket gets `lounge.sync.state` with the queue, sentiment, the last
  100 chat messages and the AI feed.
- **Playback is simulated at the scheduling level (PRD 4.2).** `startedAt × PLAYBACK_SPEED` drives the progress
  bar, the outro window (20 s) and auto-advance. When the queue empties, the AI DJ fills it from the catalogue with
  a valid segue.
- **Sentiment:** a deterministic lexicon (with negation, intensifiers, emoji and phrases). It runs in
  sub-millisecond time, so chat bursts never block the loop, and every decision is explainable. Messages are
  bucketed positive/neutral/negative. The room score is a recency-weighted mean over 30 s mapped to 0..1, ticked
  every 2 s. It feeds the energy-fit term of segue ranking: the target energy is the current energy
  + (sentiment − 0.5) × 0.5.
- **RAG:** each track's timeline is a small corpus. Retrieval is lexical overlap plus a type boost (for example,
  "sample" boosts `sample_credit`). Claude, when configured, may use only the numbered facts, and its citations are
  verified. Any unknown or missing citation sends the answer to the template path. With no relevant facts, the AI DJ
  declines instead of guessing.
- **Recommender:** score = 0.4 × content (cosine between the user's weighted acoustic profile and the track's
  vector, with key mapped onto a circle) + 0.6 × normalized item-item co-occurrence. Live listens are written as
  `interactions` when a track ends; liked = upvoted or reacted with 🔥/❤️/💯/🙌. A background job retrains every
  15 s when the interaction count changes, so the rail updates without a redeploy.
- **RBAC:** account roles are `listener`, `co_dj`, `host` and `admin`. Lounge authority is resolved *per lounge*:
  host = the lounge's current host, co_dj = granted by that host, admin = global. The WebSocket JWT is checked at
  handshake, and its expiry is re-checked on every sensitive action (`SENSITIVE` map in `gateway/ws.py`). Clients
  renew it with `auth.renew`.
- **Security:** PBKDF2-SHA256 passwords; 30-minute access tokens; rotating single-use refresh tokens (revocable in
  `refresh_tokens`); all text input stripped of markup and control characters server-side; Pydantic validation on
  every body; secrets only from env (`.env` is git-ignored).
- **Observability:** JSON logs carry `loungeId` as the correlation id for every queue event and AI decision. There
  are `/health` and `/health/gateway` endpoints, and a `Server-Timing` header on every response.

## Schema (relational, as shipped)

```mermaid
erDiagram
  users ||--o{ dj_lounges : hosts
  users ||--o{ interactions : has
  users ||--o{ refresh_tokens : owns
  tracks ||--o{ track_timeline_events : "RAG metadata"
  tracks ||--o{ interactions : ""
  dj_lounges ||--o{ queue_entries : "final queue snapshot"
  dj_lounges ||--o{ queue_events : "append-only log"
  dj_lounges ||--o{ chat_messages : ""
  dj_lounges ||--o{ soundclash_battles : ""
  soundclash_battles ||--o{ soundclash_candidates : "2..4"
  users { int id PK; string email UK; string password_hash; string display_name; string role "CHECK in 4 roles" }
  tracks { string id PK; string title; string artist; int duration_seconds; float bpm "idx, >0"; string camelot_key "idx"; float energy "idx, 0..1"; float valence "0..1" }
  track_timeline_events { string id PK; string track_id FK; int ts_seconds; string event_type "CHECK"; json payload }
  dj_lounges { string id PK; string invite_code UK; int host_user_id FK; string seed_track_id FK; string status "scheduled|live|ended"; float bpm_tolerance_pct; bool soundclash_enabled; string ai_verbosity; json summary }
  queue_entries { string id PK; string lounge_id FK; string track_id FK; int position "sparse"; int vote_count }
  queue_events { string id PK; string lounge_id FK; int user_id FK; string type; json payload; float ts }
  chat_messages { string id PK; string lounge_id FK; int user_id FK "null = AI/system"; string msg_type "CHECK"; text body; float sentiment_score }
  interactions { int id PK; int user_id FK; string track_id FK; float played_seconds; bool completed; bool liked; json co_listened_with }
```

When a Soundclash resolves, one `soundclash_battles` row and its 2–4 `soundclash_candidates` rows (with final
vote counts) are written through the batched sink, alongside the `battleResolved` event. The event log drives the
analytics counts; the battle tables drive the Ledger's per-battle list. The integration test checks that the two agree.

## Client (frontend/src)
```
main.jsx → Shell.jsx            top bar + router (History API paths, not hash links)
lib/http.js                     Session class: tokens in sessionStorage, rotating refresh, REST helpers
lib/nav.jsx                     usePath / go / Link / match — a ~50-line router
lib/room.js                     useRoom(loungeId): one WebSocket, one reducer, versioned snapshots, backoff reconnect
lib/catalog.jsx                 track catalog context + stable per-track sleeve colours
screens/  Door · Shopfront · Booth · Ledger · Workbench
booth/    Turntable · Crate · Clash · Notes · Guestbook · Crowd · MoodGauge
paper.css                       one stylesheet: forest ink on sand, colour values defined on :root
```
Every live update from the server passes through one reducer in `room.js`. A snapshot with a lower version than
the one already held is discarded, so the UI never goes backwards after a reorder. A resync after reconnecting
replaces the room state wholesale. The client only hides controls the user's role can't use; the server
enforces every permission itself (see RBAC below).

## Deviations from the PRD (and why)
| Deviation | Reason |
|---|---|
| SQLite is the default database; PostgreSQL is supported via `DATABASE_URL` | No Docker or Postgres on the build machine. The same SQLAlchemy models and CHECK constraints work on both. |
| Live lounges don't survive a server restart | Queue state is deliberately in memory (PRD 9.4). Restarted lounges are closed cleanly with a summary; resuming them would need Redis or snapshotting. |
| No audio files are played | PRD 4.2 allows scheduling-level simulation. Tracks keep an optional `audioAssetUrl`. |
| WebSocket token is sent in the query string | Browsers cannot set headers on a WS handshake. Use TLS in any non-local deployment. |
| Lexicon sentiment instead of an ML model | Deterministic, explainable, and fast enough for chat bursts. It measured 97.5% on the labelled set (see REPORT). |
| Account `role` is a badge; lounge authority is per lounge | One global "host" role would make a user host of every room. Admin stays global. |
