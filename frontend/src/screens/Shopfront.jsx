import { useEffect, useState } from 'react';
import { http } from '../lib/http.js';
import { go, Link } from '../lib/nav.jsx';
import { sleeveColour, Specs, useCatalog } from '../lib/catalog.jsx';

const VIBES = ['High-Energy EDM', 'Lo-Fi Chill', 'Deep House', 'Disco Revival', 'Liquid DnB'];

const ICONS = {
  spark: <path d="M12 2v20M2 12h20M5 5l14 14M19 5L5 19" />,
  moon: <path d="M16 3a9 9 0 1 0 5 13A7 7 0 0 1 16 3z" />,
  ticket: <path d="M3 7h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4zM14 7v10" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></>,
  note: <path d="M9 18V5l11-2v13M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zM20 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z" />,
  heart: <path d="M12 20s-7-4.5-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.5-9 9-9 9z" />,
};

// Each shelf opens one section of the shop.
const SHELVES = [
  { id: 'picks', title: 'Picked for you', no: 'LR-01', colour: '#d9533b', icon: 'spark', sub: 'Fresh picks, tailored to your vibe.' },
  { id: 'host', title: 'Host a night', no: 'LR-02', colour: '#2a2723', icon: 'moon', sub: 'Open a booth and let the room vote the crate.' },
  { id: 'invite', title: 'Got an invite', no: 'LR-03', colour: '#e3a33a', icon: 'ticket', sub: 'Someone saved you a spot on the floor.' },
  { id: 'tonight', title: 'On tonight', no: 'LR-04', colour: '#2f6b62', icon: 'sun', sub: "Booths with the lights on right now." },
  { id: 'card', title: 'Your card', no: 'LR-05', colour: '#34478a', icon: 'note', sub: 'What your listening says about you.' },
  { id: 'nights', title: 'Past nights', no: 'LR-06', colour: '#8a3a62', icon: 'heart', sub: 'Every booth you have stood in.' },
];

function Icon({ name, size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICONS[name]}</svg>
  );
}

export function Wave({ size = 26 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" fill="currentColor" aria-hidden="true">
      {[[2, 9, 8], [6, 5, 16], [10, 2, 22], [14, 6, 14], [18, 3, 20], [22, 8, 10]].map(([x, y, h]) =>
        <rect key={x} x={x} y={y} width="2.2" height={h} rx="1.1" />)}
    </svg>
  );
}

/* ---------- sections ---------- */

function PickedForYou({ picks }) {
  const { byId } = useCatalog();
  const [front, setFront] = useState(0);
  const [auto, setAuto] = useState(true);
  const count = picks.length;

  useEffect(() => {
    if (!auto || count < 2) return undefined;
    const t = setInterval(() => setFront((i) => (i + 1) % count), 4500);
    return () => clearInterval(t);
  }, [auto, count]);

  if (count === 0) return <p className="quiet">The bin is empty for now.</p>;
  const flip = (step) => setFront((i) => (i + step + count) % count);
  const current = picks[front % count];
  const track = byId[current.trackId];
  const colour = sleeveColour(current.trackId);
  const behind = [1, 2, 3].map((d) => picks[(front + d) % count]);

  return (
    <>
      <div className="pick" onKeyDown={(e) => { if (e.key === 'ArrowRight') flip(1); if (e.key === 'ArrowLeft') flip(-1); }}>
        <div className="pick-art">
          {behind.map((p, i) => (
            <span key={`${p.trackId}-${i}`} className="pick-back" style={{ '--i': i, background: sleeveColour(p.trackId) }} />
          ))}
          <span className="pick-vinyl" />
          <article key={current.trackId} className="pick-sleeve" style={{ background: colour }}>
            <span className="pick-tag">{current.popular ? 'Shop favourite' : `${Math.round(current.score * 100)}% your sound`}</span>
            <h3>{current.title}</h3>
            <p>{current.artist}</p>
            <Specs track={track} />
          </article>
        </div>

        <div className="pick-info">
          <p className="eyebrow">Front of the bin</p>
          <h2>{current.title}</h2>
          <p className="pick-artist">{current.artist}</p>
          <Specs track={track} />
          <div className="transport">
            <button className="round" onClick={() => flip(-1)} aria-label="Previous pick">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 5h2v14H6zM20 5v14L9 12z" /></svg>
            </button>
            <button className="round solid" onClick={() => setAuto((a) => !a)} aria-label={auto ? 'Stop flipping' : 'Flip automatically'}>
              {auto
                ? <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
                : <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>}
            </button>
            <button className="round" onClick={() => flip(1)} aria-label="Next pick">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16 5h2v14h-2zM4 5v14l11-7z" /></svg>
            </button>
          </div>
          <div className="position">
            <span className="position-line"><i style={{ width: `${((front % count) + 1) / count * 100}%` }} /></span>
            <span>{(front % count) + 1} of {count}</span>
            <span className="position-line" />
          </div>
        </div>
      </div>

      <div className="info-bar">
        <Wave />
        <p>{current.popular
          ? 'No listening history yet — these are what the shop plays most. Spend a night in a booth to personalise.'
          : 'Ranked on how each record sounds (tempo, key, energy) and on who you listen alongside.'}</p>
        <button className="bar-arrow" onClick={() => flip(1)} aria-label="Next pick">→</button>
      </div>
    </>
  );
}

function HostANight() {
  const { list } = useCatalog();
  const [cfg, setCfg] = useState({ seedTrackId: 't_2001', vibeProfile: VIBES[0], maxParticipants: 50,
    bpmTolerancePct: 8, soundclashEnabled: true, aiVerbosity: 'normal' });
  const [problem, setProblem] = useState(null);
  const set = (key, cast = (v) => v) => (e) =>
    setCfg((c) => ({ ...c, [key]: e.target.type === 'checkbox' ? e.target.checked : cast(e.target.value) }));

  return (
    <form className="host-form" onSubmit={async (e) => {
      e.preventDefault();
      try { go(`/booth/${(await http.post('/api/v1/lounges', cfg)).loungeId}`); }
      catch (err) { setProblem(err.message); }
    }}>
      <label className="field span-all">First record on the platter
        <select value={cfg.seedTrackId} onChange={set('seedTrackId')}>
          {list.map((t) => <option key={t.trackId} value={t.trackId}>{t.title} — {t.artist}</option>)}
        </select>
      </label>
      <label className="field span-all">Tonight's vibe
        <input list="vibe-list" value={cfg.vibeProfile} onChange={set('vibeProfile')} />
        <datalist id="vibe-list">{VIBES.map((v) => <option key={v} value={v} />)}</datalist>
      </label>
      <label className="field">Door limit
        <input type="number" min="2" max="50" value={cfg.maxParticipants} onChange={set('maxParticipants', Number)} />
      </label>
      <label className="field">Tempo leeway %
        <input type="number" min="1" max="8" step="0.5" value={cfg.bpmTolerancePct} onChange={set('bpmTolerancePct', Number)} />
      </label>
      <label className="field">DJ chattiness
        <select value={cfg.aiVerbosity} onChange={set('aiVerbosity')}>
          <option value="minimal">Quiet</option><option value="normal">Normal</option><option value="chatty">Chatty</option>
        </select>
      </label>
      <label className="switch">
        <input type="checkbox" checked={cfg.soundclashEnabled} onChange={set('soundclashEnabled')} />
        <span className="switch-track" /> Soundclash battles
      </label>
      {problem && <p className="problem span-all">{problem}</p>}
      <button className="pill-btn span-all">Open the doors <span>→</span></button>
    </form>
  );
}

function GotAnInvite() {
  const [code, setCode] = useState('');
  const [problem, setProblem] = useState(null);
  return (
    <form className="invite-form" onSubmit={async (e) => {
      e.preventDefault();
      try { go(`/booth/${(await http.get(`/api/v1/lounges/by-code/${encodeURIComponent(code.trim())}`)).loungeId}`); }
      catch (err) { setProblem(err.message); }
    }}>
      <input className="code-slot" placeholder="SP-····" value={code} maxLength={7}
        onChange={(e) => setCode(e.target.value.toUpperCase())} required aria-label="Invite code" />
      {problem && <p className="problem">{problem}</p>}
      <button className="pill-btn">Step inside <span>→</span></button>
    </form>
  );
}

function OnTonight({ rooms }) {
  const lit = rooms.filter((r) => r.participantCount > 0 || r.status === 'scheduled');
  const dark = rooms.length - lit.length;
  return (
    <div className="tonight">
      {lit.length === 0 && <p className="quiet">Every booth is dark. Be the first — host a night.</p>}
      {lit.map((r) => (
        <Link key={r.loungeId} to={`/booth/${r.loungeId}`} className="tonight-row">
          <span className="tonight-dot" style={{ background: sleeveColour(r.loungeId) }} />
          <span className="tonight-name">{r.vibeProfile}</span>
          <span className="tonight-meta">{r.participantCount} inside · {r.inviteCode}</span>
          <span className="arrow-circle">→</span>
        </Link>
      ))}
      {dark > 0 && <p className="fineprint">{dark} empty booth{dark === 1 ? '' : 's'} left open.</p>}
    </div>
  );
}

function YourCard({ taste }) {
  if (!taste) return <p className="quiet">Your card fills in once you've spent a night in a booth.</p>;
  const stats = [
    [taste.avgBpm, 'bpm on average', `${taste.bpmRange[0]}–${taste.bpmRange[1]} range`],
    [Math.round(taste.avgEnergy * 100), 'energy', 'out of 100'],
    [Math.round(taste.avgValence * 100), 'brightness', 'out of 100'],
    [taste.preferredKeys[0], 'home key', `also ${taste.preferredKeys.slice(1).join(', ')}`],
  ];
  return (
    <div className="stat-grid">
      {stats.map(([value, label, hint]) => (
        <div key={label} className="stat"><b>{value}</b><span>{label}</span><small>{hint}</small></div>
      ))}
    </div>
  );
}

function PastNights({ lounges }) {
  if (lounges.length === 0) return <p className="quiet">No nights yet.</p>;
  return (
    <div className="tonight">
      {lounges.map((lg) => (
        <div key={lg.loungeId} className="tonight-row static">
          <span className="tonight-dot" style={{ background: sleeveColour(lg.loungeId) }} />
          <span className="tonight-name">{lg.vibeProfile}</span>
          <span className="tonight-meta">{lg.hosted ? 'you hosted' : 'you came'} · {lg.status}</span>
          <span className="row-links">
            {lg.status !== 'ended' && <Link to={`/booth/${lg.loungeId}`}>back in</Link>}
            <Link to={`/ledger/${lg.loungeId}`}>ledger</Link>
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---------- page ---------- */

export default function Shopfront({ user }) {
  const [home, setHome] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [open, setOpen] = useState('picks');

  useEffect(() => {
    const refresh = () => {
      http.get('/api/v1/me/dashboard').then(setHome).catch(() => {});
      http.get('/api/v1/lounges').then(setRooms).catch(() => {});
    };
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, []);

  const shelf = SHELVES.find((s) => s.id === open);
  const content = {
    picks: <PickedForYou picks={home?.recommendations ?? []} />,
    host: <HostANight />,
    invite: <GotAnInvite />,
    tonight: <OnTonight rooms={rooms} />,
    card: <YourCard taste={home?.tasteProfile} />,
    nights: <PastNights lounges={home?.lounges ?? []} />,
  }[open];

  return (
    <div className="shop">
      <aside className="bookcase" aria-label="Shop sections">
        <p className="bookcase-title">Listening Room Collections</p>
        <div className="shelves">
          {SHELVES.map((s) => (
            <button key={s.id} className={`shelf ${open === s.id ? 'open' : ''}`} aria-pressed={open === s.id}
              onClick={() => setOpen(s.id)}>
              <span className="mini-sleeve">
                <span className="mini-cover" style={{ background: s.colour }}><Icon name={s.icon} /></span>
              </span>
              <span className="shelf-label">
                <small>{s.no}</small>
                <b>{s.title}</b>
              </span>
              <span className="arrow-circle">→</span>
            </button>
          ))}
        </div>
        <p className="bookcase-foot">— Six collections. Endless vibes. —</p>
      </aside>

      <section key={open} className="section-view" aria-live="polite">
        <header className="section-head">
          <p className="section-no">{shelf.no}</p>
          <h1>{shelf.title}</h1>
          <p className="section-sub">{shelf.sub}</p>
          <p className="scrawl" aria-hidden="true">Good Music<br />Better Days</p>
        </header>
        <div className="section-body">{content}</div>
      </section>
    </div>
  );
}
