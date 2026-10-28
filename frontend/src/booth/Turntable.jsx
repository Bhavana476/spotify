import { useEffect, useState } from 'react';
import { sleeveColour, Specs, useCatalog } from '../lib/catalog.jsx';

function useClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  return now;
}

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export default function Turntable({ snapshot, crew, emit }) {
  const { byId } = useCatalog();
  const now = useClock();
  const np = snapshot.nowPlaying;
  const track = np && byId[np.trackId];
  const live = snapshot.status === 'live';
  const speed = snapshot.settings.playbackSpeed || 1;
  const elapsed = np ? Math.max(0, (now / 1000 - np.startedAt) * speed) : 0;
  const share = track ? Math.min(1, elapsed / track.durationSeconds) : 0;
  const outro = track && track.durationSeconds - elapsed <= snapshot.settings.outroWindowSeconds;
  // Tonearm swings from the record's outer edge (−24°) toward the label (+6°) as the track plays.
  const armAngle = -24 + share * 30;

  return (
    <section className="deck">
      <div className="platter">
        <svg viewBox="0 0 240 240" className={`record ${live && track ? 'spinning' : ''}`} aria-hidden="true">
          <circle cx="120" cy="120" r="116" fill="#1b1a17" />
          {[104, 92, 80, 68, 56].map((r) => <circle key={r} cx="120" cy="120" r={r} fill="none" stroke="#34322c" strokeWidth="1" />)}
          <circle cx="120" cy="120" r="40" fill={track ? sleeveColour(track.trackId) : '#bdb4a2'} />
          <text x="120" y="116" textAnchor="middle" className="record-label">{track ? track.artist.slice(0, 14) : 'NO DISC'}</text>
          <text x="120" y="132" textAnchor="middle" className="record-label small">{track ? `${track.acoustic.camelotKey} · ${track.acoustic.bpm}` : ''}</text>
          <circle cx="120" cy="120" r="3" fill="#f4efe4" />
        </svg>
        <svg viewBox="0 0 120 200" className="tonearm" style={{ transform: `rotate(${armAngle}deg)` }} aria-hidden="true">
          <circle cx="90" cy="20" r="14" fill="#cfc6b3" stroke="#f4efe4" strokeWidth="2" />
          <path d="M90 20 L70 150 L52 172" fill="none" stroke="#d8cfbd" strokeWidth="5" strokeLinecap="round" />
          <rect x="40" y="166" width="22" height="14" rx="3" fill="#e2553f" transform="rotate(-35 51 173)" />
        </svg>
      </div>

      <div className="deck-meta">
        <p className="kicker">{live ? 'Spinning now' : snapshot.status === 'ended' ? 'Set over' : 'Needle up'}</p>
        {track ? (
          <>
            <h2 className="deck-title">{track.title}</h2>
            <p className="deck-artist">{track.artist}</p>
            <Specs track={track} />
            <div className="groove" role="progressbar" aria-valuenow={Math.round(share * 100)}>
              <div className="groove-fill" style={{ width: `${share * 100}%` }} />
              <div className="groove-outro"
                style={{ left: `${(1 - snapshot.settings.outroWindowSeconds / track.durationSeconds) * 100}%` }}
                title="Outro window — the AI DJ picks the next record here" />
            </div>
            <p className="timecode">{mmss(elapsed)} / {mmss(track.durationSeconds)} {outro && <em>· in the outro</em>}</p>
          </>
        ) : <p className="deck-artist">Waiting for the host to drop the needle.</p>}

        <div className="deck-buttons">
          {!live && crew.isHost && snapshot.status !== 'ended' &&
            <button className="btn ink" onClick={() => emit('playback.start')}>Drop the needle</button>}
          {live && <button className="btn" onClick={() => emit('track.like')}>♥ Love this record</button>}
          {live && crew.isCrew && <>
            <button className="btn" onClick={() => emit('playback.seek_outro')} title="Skip ahead so the AI DJ chooses now">Cue the outro</button>
            <button className="btn" onClick={() => emit('playback.skip')}>Next record</button>
          </>}
        </div>
      </div>
    </section>
  );
}
