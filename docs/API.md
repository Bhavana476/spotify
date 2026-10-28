# API reference

The base URL is `/api/v1`. All endpoints except register, login and refresh need `Authorization: Bearer <accessToken>`.
Errors look like `{"detail": "..."}`. Validation errors return 422 with `{"detail":"Validation failed","errors":[{"field":"acoustic.camelotKey","message":"Value error, '13C' is not a valid Camelot key (expected 1A-12B)"}]}`.
Interactive OpenAPI docs are served at `/docs` while the server runs. An importable Postman collection
covering every endpoint below is in [postman_collection.json](postman_collection.json) (regenerate with
`python docs/make_postman.py`).

## Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | `{email, password(≥8), displayName}` → 201 `{accessToken, refreshToken, tokenType, user}` |
| POST | `/auth/login` | `{email, password}` → same shape |
| POST | `/auth/refresh` | `{refreshToken}` → new pair. Refresh tokens are single-use, so a replay returns 401. |
| POST | `/auth/logout` | `{refreshToken}` → 204 (revokes the token) |
| GET | `/auth/me` | current user |

## Tracks
| Method | Path | Notes |
|---|---|---|
| GET | `/tracks?q=` | catalogue without timelines |
| GET | `/tracks/{id}/acoustic-profile` | PRD 7.3.2 `{trackId,title,artist,durationSeconds,acoustic:{bpm,camelotKey,energy,valence},timeline:[{id,ts,type,text}]}` |
| GET | `/tracks/{id}/compatible?sentiment=&tolerance=` | every rule-valid segue from this track, ranked, with match reasons |

## Lounges
| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/lounges` | any | PRD 7.3.1. Body `{seedTrackId, vibeProfile, maxParticipants≤50, bpmTolerancePct≤8, soundclashEnabled, aiVerbosity: minimal\|normal\|chatty}` → 201 `{loungeId, inviteCode, status, hostUserId, createdAt}` |
| GET | `/lounges` | any | open lounges with participant counts |
| GET | `/lounges/by-code/{code}` | any | resolve an invite code |
| GET | `/lounges/{id}` | any | lounge plus live state snapshot and summary |
| POST | `/lounges/{id}/start` · `/end` | host | start the set / end and persist the summary |
| POST | `/lounges/{id}/queue/{entryId}/promote` | co_dj | pin an entry to Next Up |
| POST | `/lounges/{id}/ai/segue` | co_dj | PRD 7.3.3 (example below). Add `"apply": true` to run the live decision and broadcast it. Returns 409 if no candidate is valid. |
| POST | `/lounges/{id}/ai/ask` | any | `{question, trackId?}` → `{answer, sourceEvents, sources, grounded, generator, latencyMs}` |
| GET | `/lounges/{id}/chat?limit=` | any | persisted chat history |
| GET | `/lounges/{id}/analytics` | participant/host/admin | duration, peak participants, battles, AI questions, chat, votes, segues, AI P95, `sentimentTimeline[{t,score,samples}]`, `battles[{battleId, openedAt, winningTrackId, candidates[{trackId, votes, submittedBy}]}]` |

`POST /lounges/{id}/ai/segue`:
```json
// request
{"currentTrackId":"t_2001","currentTs":198,"candidateTrackIds":["t_2002","t_2003","t_2004"],"currentSentimentScore":0.72}
// 200
{"selectedTrackId":"t_2003","aiSelected":true,
 "matchReason":{"bpmDeltaPct":0.81,"bpmRelation":"same","camelotRelation":"identical","energyFit":0.88,
                "harmonicCloseness":1.0,"recency":1.0,"score":0.964},
 "transitionScript":"Room's on fire — keeping the energy climbing: out of \"Night Drive\" into \"Pulse Theory\" by Kairo Vance, locked in the same key, 8A, at 125 BPM. Fun fact: The clap layer comes from a field recording of a stadium crowd in Buenos Aires.",
 "sourceEvents":["evt_2003_2"],"generator":"template","alternatives":["t_2004"],
 "generatedAt":"2026-10-27T10:24:47Z","latencyMs":0.3}
```

## Dashboard
| GET | `/me/dashboard` | `{user, lounges[], activeLounges[], tasteProfile{bpmRange,avgBpm,avgEnergy,avgValence,preferredKeys}, recommendations[]}` |
|---|---|---|
| GET | `/me/recommendations?k=` | `{items:[{trackId,score,contentScore,cfScore,title,...}], model:{interactions,trainedAt}}` |

## Admin (admin role only)
| Method | Path | Notes |
|---|---|---|
| PUT | `/admin/tracks` | create or replace `{trackId?, title, artist, durationSeconds, audioAssetUrl?, acoustic{bpm>0, camelotKey∈1A..12B, energy 0..1, valence 0..1}, timeline[{ts,type,text}]}` |
| POST | `/admin/tracks/validate` | dry-run validation |
| DELETE | `/admin/tracks/{id}` | |
| GET | `/admin/users` · PATCH `/admin/users/{id}/role` | `{role}` |
| POST | `/admin/recommender/retrain` | force a retrain |

Health checks: `GET /health`, `GET /health/gateway`.

## WebSocket — `/ws/lounges/{loungeId}?token=<accessToken>`
Close codes: 4401 bad token · 4404 unknown lounge · 4403 locked, full, banned or removed · 4410 / 4000 lounge ended.

**Server → client** envelope: `{"event", "loungeId", "payload", "ts" (server ms), "version"}`
| Event | Payload |
|---|---|
| `lounge.sync.state` | full snapshot (below) + `chatHistory`, `aiFeed`, sent on every (re)join |
| `lounge.queue.update` | full snapshot + `reason`: vote, add, segue, battle, advance, override, presence, host, moderation, start, ended, seek |
| `lounge.presence.update` | `{participantId, displayName?, action: joined\|left, participantCount}` |
| `lounge.presence.list` | `{participants[{userId, displayName, rttMs, muted, role}]}` (every 5 s) |
| `lounge.chat.message` | `{messageId, userId, displayName, body, msgType: chat\|ai_answer\|system, sentimentBucket, sentimentScore, tsSeconds}`. AI answers add `question, askedBy, sourceEvents, sources, grounded` |
| `lounge.chat.typing` / `lounge.chat.reaction` | `{userId, displayName, typing}` / `{messageId, emoji, userId}` |
| `lounge.sentiment.score` | `{rollingScore 0..1, windowSeconds, sampleSize}` |
| `lounge.soundclash.open` | `{battleId, candidateTrackIds, closesAt}` |
| `lounge.soundclash.resolved` | `{battleId, winningTrackId, tally, tieBreak: null\|host\|ai}` |
| `lounge.ai.dj_announcement` | `{text, relatedTrackId, sourceEvents, kind: segue\|battle}` |
| `lounge.sync.pong` | `{clientSentAt, serverReceivedAt}` |
| `lounge.ack` / `lounge.error` | `{requestId}` / `{code, message, requestId, forEvent}`. Codes: forbidden, frozen, token_expired, invalid, duplicate, battle_active, muted… |

Snapshot fields: `version, status, hostUserId, hostState, frozen, locked, coDjIds, settings, nowPlaying{entryId,trackId,startedAt}, queue[{entryId,trackId,position,sparsePosition,votes,voterIds,addedBy,locked}], soundclash, lastBattle, submissions, pendingSegue, history, participants, serverTime, sentiment`.

**Client → server** messages: `{"event", "payload", "requestId"?}` (role in brackets; the default is any participant)
`chat.send{body}` · `chat.typing{typing}` · `chat.react{emoji}` · `track.like` · `queue.add{trackId}` · `queue.vote{entryId, up}` ·
`soundclash.submit{trackId}` · `soundclash.vote{trackId}` · `ai.ask{question, trackId?}` · `sync.ping{clientSentAt, lastRttMs}` · `auth.renew{token}` ·
[co_dj] `queue.promote{entryId}` `queue.remove{entryId}` `soundclash.open` `soundclash.resolve{trackId?}` `ai.segue.request` `ai.segue.approve` `ai.segue.reject` `playback.skip` `playback.seek_outro` ·
[host] `playback.start` `mod.mute|mod.unmute|mod.remove{userId}` `mod.lock{locked}` `mod.set_role{userId, role: co_dj|listener}` `mod.transfer_host{userId}` `lounge.end`
