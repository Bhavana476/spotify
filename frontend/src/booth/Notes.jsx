import { useCatalog } from '../lib/catalog.jsx';

const RELATION = { identical: 'same key', relative: 'relative major/minor', adjacent: 'one step round the wheel' };
const TEMPO = { same: 'same tempo', half_time: 'half-time', double_time: 'double-time' };

function Decision({ pending, crew, emit }) {
  const { byId } = useCatalog();
  const t = byId[pending.selectedTrackId];
  const why = pending.matchReason;
  return (
    <div className={`decision ${pending.aiSelected ? '' : 'override'}`}>
      <p className="kicker">Next mix · {pending.status}</p>
      <p className="decision-track"><b>{t?.title}</b> <span className="by">{t?.artist}</span></p>
      {pending.aiSelected ? (
        <dl className="why">
          <div><dt>Key</dt><dd>{RELATION[why.camelotRelation]}</dd></div>
          <div><dt>Tempo</dt><dd>{TEMPO[why.bpmRelation]} · Δ{why.bpmDeltaPct}%</dd></div>
          <div><dt>Energy fit</dt><dd>{Math.round(why.energyFit * 100)}%</dd></div>
          <div><dt>Decided in</dt><dd>{pending.latencyMs} ms</dd></div>
        </dl>
      ) : <p className="quiet">The crowd's choice — not a clean mix, so the DJ says so instead of pretending.</p>}
      {crew.isCrew && pending.status === 'pending' && (
        <div className="row-gap">
          <button className="btn ink" onClick={() => emit('ai.segue.approve')}>Approve</button>
          <button className="btn" onClick={() => emit('ai.segue.reject')}>Try another</button>
        </div>
      )}
    </div>
  );
}

export default function Notes({ snapshot, notes, crew, emit }) {
  const pending = snapshot.pendingSegue;
  return (
    <section className="panel notes-panel">
      <header className="panel-head">
        <h3>DJ's notes</h3>
        <span className="aside">every claim cites the track's liner notes</span>
      </header>
      {pending?.selectedTrackId && <Decision pending={pending} crew={crew} emit={emit} />}
      {crew.isCrew && snapshot.status === 'live' && !pending &&
        <button className="text-btn" onClick={() => emit('ai.segue.request')}>Ask the DJ to plan the next mix</button>}
      <ol className="corkboard">
        {[...notes].reverse().map((n, i) => (
          <li key={`${n.ts}-${i}`} className={`note ${n.kind}`} style={{ '--tilt': `${((i * 7) % 5) - 2}deg` }}>
            <span className="note-kind">{n.kind === 'battle' ? 'clash result' : 'transition'}</span>
            <p>{n.text}</p>
            {n.sourceEvents?.length > 0 && <span className="cite">source: {n.sourceEvents.join(', ')}</span>}
          </li>
        ))}
        {notes.length === 0 && <li className="quiet">The DJ will pin notes here as records change.</li>}
      </ol>
    </section>
  );
}
