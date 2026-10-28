# Test report, performance evidence & retrospective

## Automated tests: `python -m pytest -q` → **77 passed**
| File | What it proves |
|---|---|
| `test_acoustic.py` (33) | 24-key Camelot parsing; every relation, including the 12↔1 wrap; ±8% boundaries (110.4/129.6 pass, 110.3/129.7 fail); half- and double-time. **500 random segue decisions checked against an independently written oracle: 100% rule-compliant.** Engine and oracle agree on all 600 catalogue pairs. The AI DJ decision path stays valid across 30 runs. An invalid human override is never labelled `aiSelected`. |
| `test_sentiment.py` (6) | **Accuracy 78/80 = 97.5%** on a hand-labelled set of 80 messages (`tests/data/sentiment_test.json`, target ≥85%). The set was written before the first measurement and the lexicon was not tuned against it. Also covers negation, intensifiers, bounds, and a rolling-window shift after a negative burst. |
| `test_rag.py` (6) | Answers cite the right entries. It declines when nothing matches. Answers contain only retrieved text. The citation verifier rejects made-up ids. Transition scripts are grounded in the next track's metadata. |
| `test_queue_state.py` (12) | Idempotent votes; sparse positions (only the moved row changes); **30 concurrent voters → one consistent order, strictly ordered versions**; capacity, lock and ban; reconnect grace; host disconnect promotes a Co-DJ or freezes; full Soundclash flow plus the tie-break rules. |
| `test_integration.py` (8) | Real HTTP + WS. API contracts match PRD 7.3; upload validation; refresh rotation; two clients get the identical queue at the identical version after a vote; a mid-session join syncs in under 2 s; Soundclash end-to-end; AI segue; grounded Q&A; sentiment drop; XSS stripping; host-disconnect freeze; **analytics reconcile exactly with the event log, and the persisted `soundclash_battles` rows agree with it**; dashboard and recommendations. |
| `test_rbac.py` (9) | Unauthenticated requests get 401. Acoustic upload by listener, co-DJ or host gets 403; by admin, 201. Segue, start and end are scoped to the lounge role. Over WS, a listener gets `forbidden` on 5 privileged events; a Co-DJ is allowed segue but forbidden host actions; an admin is allowed everywhere. |
| `test_recommender.py` (2) | A brand-new listener gets popularity-ranked picks, not identical flat scores; a listener with history is never given the popularity fallback. |
| `test_recovery.py` (1) | After a restart, orphaned `live` lounges and stale unstarted lounges are closed with a summary; a fresh scheduled lounge is left alone. |

## Browser tests: `python -m pytest tests_ui -q` → **6 passed** (Edge, against the running server)
| Test | What it proves |
|---|---|
| `test_shopfront_every_shelf_opens_its_section` | All six shelves open their section; the recommendation bin flips. |
| `test_brand_new_member_gets_shop_favourites_not_flat_scores` | A freshly registered account sees "Shop favourite" picks. |
| `test_two_members_one_booth_end_to_end` | Two browsers in one lounge: a vote reorders both crates; a grounded answer cites `evt_2001_1`; a Soundclash winner takes the next slot on both screens; the AI DJ plans the mix; ending the night shows the battle in the Ledger. |
| `test_workbench_rejects_bad_profile_and_files_good_one` | Admin Workbench: Camelot key `13C` is refused with the reason and the field highlighted; a valid profile is filed (then deleted). |
| `test_listener_has_no_workbench` | A listener sees no Workbench link, and `/workbench` falls back to the Shopfront. |
| `test_phone_width_never_scrolls_sideways` | At 390 px wide there is no horizontal scroll. |

Every browser test also fails if the page throws a JavaScript error.

## Postman collection: `docs/postman_collection.json` → **34 of 34 requests pass**
Run top to bottom, it covers every REST endpoint. That includes the 403 role checks, the 422 validation, the 409
"no rule-valid segue" refusal, and refresh-token revocation (401). It was verified by replaying it against the
running server.

## Measured performance (`scripts/crowd_sim.py`, 10 WebSocket clients, one Windows laptop, SQLite) → `docs/perf-results.json`
| PRD 10.2 dimension | Target | Measured |
|---|---|---|
| Queue sync drift (spread of one update's arrival across clients, under 10 simultaneous votes) | < 100 ms | **p95 17.4 ms**, max 17.4 ms |
| WS fan-out (server send → last client) | < 500 ms | **p95 88 ms**, max 94 ms |
| API latency, non-AI (100 requests) | P95 < 200 ms | **P95 43 ms** |
| AI DJ segue decision + transition script (30 requests, template generator) | P95 < 3 s | **P95 88 ms** |
| Mid-session join / reconnect resync | < 2 s | **25 ms**, chat history restored |
| Sentiment reacts to a negative burst | within one window | 0.93 → **0.28** in **2.1 s** |
| Concurrent votes | all clients agree | ✅ same final order and version on all 10 clients |
| Recommender Precision@5 (`scripts/eval_recommender.py`, 55 users, 5 held-out positives each) | ≥ 0.6 | **0.644** (content-only 0.527, CF-only 0.636, popularity 0.302) |

Timings vary between runs on the same machine: across three runs, API P95 ranged 20–43 ms and sync drift 7–32 ms.
All runs stayed well under target; the table shows the run saved in `perf-results.json`.

Honest caveats:
- These are localhost numbers with 10 clients, not the 50-person design capacity.
- AI latency was measured on the template path. With `ANTHROPIC_API_KEY` set, a 2.5 s timeout guarantees a fallback inside the 3 s budget, but the LLM path was not benchmarked here, and the default model name in `.env.example` has not been verified against a live API.
- Only SQLite has been run. The PostgreSQL path (`asyncpg`) is configured but untested.
- The recommender dataset is synthetic and clustered by design, so P@5 reflects that structure.
- Running against `localhost` instead of `127.0.0.1` on Windows added about 2 s per new connection (IPv6 fallback). That is a client resolver issue, not a server one.

## Retrospective
**Built:** everything in Epics 1–3, end to end:
- Auth with refresh rotation, and four-role RBAC over HTTP and WS.
- A live queue state machine with votes, pins, Soundclash battles (with tie-break), presence, reconnect grace, moderation and a host-disconnect policy.
- An acoustic matcher with hard constraints and weighted ranking.
- A sentiment pipeline that steers segue energy.
- RAG banter and Q&A with verified citations, plus an optional Claude generator.
- A hybrid recommender with background retraining and a popularity fallback for new listeners.
- Analytics from the event log, persisted Soundclash history, an admin Workbench, and a React client designed as a record shop.

**Descoped / deviations:** see [ARCHITECTURE.md](ARCHITECTURE.md#deviations-from-the-prd-and-why).
In short: SQLite is the default DB, there is no real audio playback, and live lounges don't survive a server restart
(they are closed cleanly instead).

**Still outstanding:**
- A recorded walkthrough video (PRD 12.2). It has to be screen-recorded by hand; the demo path is in the README.
- A run with a real `ANTHROPIC_API_KEY`, and a run on PostgreSQL.

**Next, with more time:**
- Use Redis pub/sub (and snapshots) so gateway instances can scale horizontally and lounges survive restarts.
- Load-test at 50 clients with latency histograms.
- Benchmark the LLM path and add streaming banter.
- Embedding-based retrieval once timelines grow.
- Learn the sentiment→energy curve from interaction data instead of a fixed slope.
