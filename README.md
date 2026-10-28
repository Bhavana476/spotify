# AI DJ Studio — Collaborative Live Queue Curation & Sentiment-Aware Audio Engine

A real-time "DJ Lounge": a shared queue that reorders live as people vote, Soundclash battles between
challenger tracks, chat whose mood is scored continuously, and an AI DJ. The AI DJ picks only
harmonically valid segues (BPM ±8% / half- and double-time, Camelot wheel) and explains each pick with
banter grounded in the track's metadata.

**Stack:** Option C (Python): FastAPI + native WebSockets + SQLAlchemy (async) + React (Vite, JavaScript).
**Track:** A (Full-Stack). The client is styled as a record shop called **The Listening Room**.

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture as built, client structure, ER diagram, design decisions, deviations from the PRD |
| [docs/API.md](docs/API.md) | Every REST endpoint and WebSocket event, with example payloads |
| [docs/postman_collection.json](docs/postman_collection.json) | Importable Postman collection (34 requests, each with a status check) |
| [docs/REPORT.md](docs/REPORT.md) | Test report, measured performance against PRD 10.2, retrospective |

## Quick start (Windows / macOS / Linux)

Prerequisites: Python 3.11+ and Node 18+. No database server is needed: SQLite is the default, and PostgreSQL is optional.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then set JWT_SECRET to a long random string
python seed.py --reset            # 25 tracks, 5 demo users, ~820 synthetic interactions

# 2. Frontend (build once; the backend serves it)
cd ../frontend
npm install
npm run build

# 3. Run
cd ../backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Use `127.0.0.1` rather than `localhost` on Windows: `localhost` adds about 2 s to
each new connection there. For frontend hot-reload, run `npm run dev` in `frontend/` and open
<http://localhost:5173>. Vite proxies `/api` and `/ws` to the backend.

**Demo accounts** (password = `SEED_PASSWORD`, default `djstudio-demo`. This is a local-only demo credential):
`admin@djstudio.dev`, `host@djstudio.dev`, `codj@djstudio.dev`, `listener@djstudio.dev`, `guest@djstudio.dev`.

**PostgreSQL:** set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/djstudio` in `.env` and re-run `seed.py --reset`.

**Real LLM banter (optional):** set `ANTHROPIC_API_KEY`. Without a key, or if the call times out, the
AI DJ falls back to deterministic templates built from the same retrieved metadata. Answers are still
grounded and cited either way.

## Finding your way around the client

| Screen | Path | What it is |
|---|---|---|
| The Door | `/` (signed out) | Sign in or register |
| Shopfront | `/` | The dashboard. A bookcase of six shelves on the left; each opens one section on the right |
| The Booth | `/booth/<loungeId>` | A live lounge: turntable, crate (queue), Soundclash, DJ's notes, Guestbook (chat), who's on the floor |
| Ledger | `/ledger/<loungeId>` | Session analytics: counts, mood chart, Soundclash results |
| Workbench | `/workbench` (admin only) | Upload or edit a track's acoustic profile and liner notes |

The Shopfront shelves are **Picked for you** (recommendations, flipped one at a time), **Host a night**
(create a lounge), **Got an invite** (join by code), **On tonight** (open lounges), **Your card**
(acoustic taste profile) and **Past nights** (history, with rejoin and ledger links).

## 5-minute demo path
1. Window A: sign in as **host**. Open the **Host a night** shelf and press **Open the doors**. Copy the invite code
   shown next to the lounge name.
2. Window B, a private window (sessions are per tab): sign in as **listener**. Open **Got an invite**, type the code
   and press **Step inside**.
3. Host: **Drop the needle**. Add a few records to the crate with **Add to crate**. When B presses **vote** on one,
   both crates reorder at the same moment.
4. B: pick a challenger in **Soundclash** and press **Challenge**. After about 8 s the AI DJ opens the battle
   (or the host presses **Ring the bell now**). B presses **Back this one**, then the host presses
   **Close voting now**. The winner takes the next slot, stamped "Won the clash", and the DJ pins a note about it.
5. Host: **Cue the outro**. The AI DJ plans a rule-valid mix and shows why (key, tempo, energy fit), then pins a
   grounded note. **Approve** it, or **Try another** for the next best.
6. B: switch the Guestbook to **Ask the DJ** and type "where's this sample from?". The answer cites `evt_2001_1`.
7. B: send lines like "so boring 😴" and "skip this". The mood gauge needle drops within about 2 s.
8. Host: **End the night**, then open Shopfront → **Past nights** → **ledger** for the mood chart and the
   Soundclash result.

The same path is scripted for 10 clients: `python -m scripts.crowd_sim --clients 10` (server must be running).

## Tests
```bash
cd backend
python -m pytest -q                       # 77 unit + integration tests (no server needed)
python -m pytest tests_ui -q              # 6 browser tests; needs the server running and Edge installed
python -m scripts.eval_recommender        # offline Precision@5
```
The browser tests use the locally installed Microsoft Edge. On a machine without Edge, run
`python -m playwright install chromium` and set `UI_BROWSER_CHANNEL=chromium`.

To exercise the REST API by hand, import `docs/postman_collection.json` into Postman and run it top to bottom.
Each request saves the tokens and IDs that later ones need.
