import { useEffect, useState } from 'react';
import { http } from '../lib/http.js';
import { sleeveColour, useCatalog } from '../lib/catalog.jsx';

function useSeconds() {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 500); return () => clearInterval(t); }, []);
  return now;
}

// Tracks that mix cleanly out of the current record, used to warn people before they submit a clash.
function useSafeSet(trackId) {
  const [safe, setSafe] = useState(new Set());
  useEffect(() => {
    if (!trackId) return;
    http.get(`/api/v1/tracks/${trackId}/compatible`).then((rows) => setSafe(new Set(rows.map((r) => r.trackId)))).catch(() => {});
  }, [trackId]);
  return safe;
}

export default function Clash({ snapshot, crew, emit }) {
  const { byId, list } = useCatalog();
  const now = useSeconds();
  const safe = useSafeSet(snapshot.nowPlaying?.trackId);
  const [pick, setPick] = useState('');
  if (!snapshot.settings.soundclashEnabled) return null;

  const battle = snapshot.soundclash;
  const total = battle ? Object.values(battle.tally).reduce((a, b) => a + b, 0) : 0;

  return (
    <section className="panel clash-panel">
      <header className="panel-head">
        <h3>Soundclash</h3>
        {battle && <span className="aside">{battle.status === 'tied' ? 'Dead heat — crew decides'
          : `closes in ${Math.max(0, Math.ceil(battle.closesAt - now))}s`}</span>}
      </header>

      {battle ? (
        <div className="versus">
          {battle.candidates.map((c, i) => {
            const t = byId[c.trackId];
            const votes = battle.tally[c.trackId] || 0;
            return (
              <div key={c.trackId} className="contender">
                {i > 0 && <span className="vs">vs</span>}
                <div className="contender-card" style={{ '--sleeve': sleeveColour(c.trackId) }}>
                  <span className="corner">{c.defender ? 'Defending' : 'Challenger'}</span>
                  <strong>{t?.title}</strong>
                  <span className="by">{t?.artist}</span>
                  <span className={safe.has(c.trackId) ? 'fit good' : 'fit bad'}>
                    {safe.has(c.trackId) ? 'mixes in key' : 'would clash'}
                  </span>
                  <div className="tally">
                    <div style={{ height: `${total ? (votes / total) * 100 : 0}%` }} />
                  </div>
                  <span className="count">{votes} vote{votes === 1 ? '' : 's'}</span>
                  {battle.status === 'open' && <button className="btn" onClick={() => emit('soundclash.vote', { trackId: c.trackId })}>Back this one</button>}
                  {battle.status === 'tied' && crew.isCrew &&
                    <button className="btn ink" onClick={() => emit('soundclash.resolve', { trackId: c.trackId })}>Crown it</button>}
                </div>
              </div>
            );
          })}
          {battle.status === 'open' && crew.isCrew &&
            <button className="text-btn wide" onClick={() => emit('soundclash.resolve')}>Close voting now</button>}
        </div>
      ) : (
        <>
          <p className="quiet">Think something should beat the next record? Put it up against it — the room votes.</p>
          {snapshot.submissions.length > 0 && (
            <ul className="waiting">
              {snapshot.submissions.map((s) => <li key={s.trackId}>{byId[s.trackId]?.title} <em>waiting for the bell</em></li>)}
            </ul>
          )}
          {snapshot.lastBattle && (
            <p className="quiet">Last winner: <b>{byId[snapshot.lastBattle.winningTrackId]?.title}</b></p>
          )}
          <form className="inline-form" onSubmit={(e) => {
            e.preventDefault();
            if (pick) { emit('soundclash.submit', { trackId: pick }); setPick(''); }
          }}>
            <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Challenger">
              <option value="">Pick a challenger…</option>
              {list.map((t) => (
                <option key={t.trackId} value={t.trackId}>{safe.has(t.trackId) ? '✓ ' : '✗ '}{t.title} ({t.acoustic.camelotKey})</option>
              ))}
            </select>
            <button className="btn ink" disabled={!pick}>Challenge</button>
          </form>
          {crew.isCrew && snapshot.submissions.length > 0 &&
            <button className="text-btn" onClick={() => emit('soundclash.open')}>Ring the bell now</button>}
        </>
      )}
    </section>
  );
}
