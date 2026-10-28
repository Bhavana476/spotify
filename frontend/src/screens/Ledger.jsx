import { useEffect, useState } from 'react';
import { http } from '../lib/http.js';
import { useCatalog } from '../lib/catalog.jsx';

function MoodTrace({ points }) {
  if (points.length === 0) return <p className="quiet">No mood readings were taken this night.</p>;
  const W = 700, H = 200, pad = 34, right = 80; // right margin leaves room for the "flagging" label
  const end = Math.max(...points.map((p) => p.t), 1);
  const px = (t) => pad + (t / end) * (W - pad - right);
  const py = (s) => H - pad - s * (H - pad * 2);
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${px(p.t).toFixed(1)} ${py(p.score).toFixed(1)}`).join(' ');
  const area = `${line} L${px(points.at(-1).t).toFixed(1)} ${py(0)} L${px(points[0].t).toFixed(1)} ${py(0)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="trace" role="img" aria-label="Room mood across the night">
      {[['hyped', 1], ['neutral', 0.5], ['flagging', 0]].map(([name, v]) => (
        <g key={name}>
          <line x1={pad} x2={W - right} y1={py(v)} y2={py(v)} className="rule" />
          <text x={W - right + 8} y={py(v) + 4} className="tick-label">{name}</text>
        </g>
      ))}
      <path d={area} className="trace-fill" />
      <path d={line} className="trace-line" />
      {points.map((p, i) => (
        <circle key={i} cx={px(p.t)} cy={py(p.score)} r="3.5" className="trace-dot">
          <title>{`${p.t}s — ${p.score} from ${p.samples} messages`}</title>
        </circle>
      ))}
      <text x={pad} y={H - 8} className="tick-label">doors</text>
      <text x={W - right} y={H - 8} className="tick-label" textAnchor="end">{Math.round(end)}s</text>
    </svg>
  );
}

export default function Ledger({ loungeId }) {
  const { byId } = useCatalog();
  const [ledger, setLedger] = useState(null);
  const [problem, setProblem] = useState(null);
  useEffect(() => { http.get(`/api/v1/lounges/${loungeId}/analytics`).then(setLedger).catch((e) => setProblem(e.message)); }, [loungeId]);

  if (problem) return <div className="closed-sign"><h2>Ledger unavailable</h2><p>{problem}</p></div>;
  if (!ledger) return <div className="closed-sign"><h2>Opening the ledger…</h2></div>;

  const lines = [
    ['Length of the night', `${Math.round(ledger.durationSeconds / 60)} min`],
    ['Most people on the floor', ledger.peakConcurrentParticipants],
    ['Records played', ledger.tracksPlayed],
    ['Soundclashes', ledger.soundclashBattles],
    ['Questions for the DJ', ledger.aiQuestionsAsked],
    ['Guestbook lines', ledger.chatMessages],
    ['Votes cast', ledger.votes],
    ['Mixes chosen by the DJ', ledger.aiSegues],
    ['Slowest DJ decision (p95)', ledger.aiSegueLatencyP95Ms != null ? `${ledger.aiSegueLatencyP95Ms} ms` : '—'],
  ];

  return (
    <article className="ledger">
      <header>
        <p className="kicker">Ledger · {ledger.lounge.status}</p>
        <h1>{ledger.lounge.vibeProfile}</h1>
      </header>
      <table className="ledger-table">
        <tbody>{lines.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody>
      </table>
      <h3>How the room felt</h3>
      <MoodTrace points={ledger.sentimentTimeline} />
      <h3>Soundclashes</h3>
      {ledger.battles.length === 0 ? <p className="quiet">No records went head to head this night.</p> : (
        <ol className="battle-list">
          {ledger.battles.map((b) => {
            const [top, ...rest] = b.candidates;
            return (
              <li key={b.battleId}>
                <span className="winner">🏆 {byId[b.winningTrackId]?.title ?? b.winningTrackId}</span>
                <span className="rest">{top?.votes ?? 0} votes{rest.length > 0 && ' · beat '}
                  {rest.map((c) => `${byId[c.trackId]?.title ?? c.trackId} (${c.votes})`).join(', ')}</span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="fineprint">Tallied from {ledger.eventCount} entries in the night's event log.</p>
    </article>
  );
}
