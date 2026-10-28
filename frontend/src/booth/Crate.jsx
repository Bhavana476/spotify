import { useState } from 'react';
import { sleeveColour, Specs, useCatalog } from '../lib/catalog.jsx';

const PIN_LABEL = { segue: 'AI DJ pick', battle: 'Won the clash', host: 'Host pick' };

export default function Crate({ snapshot, me, crew, emit }) {
  const { byId, list } = useCatalog();
  const [choice, setChoice] = useState('');
  const queued = new Set(snapshot.queue.map((q) => q.trackId));

  const add = (e) => {
    e.preventDefault();
    if (!choice) return;
    emit('queue.add', { trackId: choice });
    setChoice('');
  };

  return (
    <section className="panel crate">
      <header className="panel-head">
        <h3>The crate</h3>
        <span className="aside">{snapshot.queue.length} records waiting · most votes play first</span>
      </header>

      {snapshot.queue.length === 0 && (
        <p className="quiet">Crate's empty. When this record ends the AI DJ pulls one that mixes in key.</p>
      )}

      <div className="sleeves">
        {snapshot.queue.map((entry, i) => {
          const t = byId[entry.trackId];
          const mine = entry.voterIds.includes(me);
          return (
            <article key={entry.entryId} className={`sleeve ${entry.locked ? 'pinned' : ''}`}>
              <div className="sleeve-art" style={{ background: sleeveColour(entry.trackId) }}>
                <span>{i === 0 ? 'NEXT' : `#${i + 1}`}</span>
              </div>
              <div className="sleeve-body">
                <strong>{t?.title ?? entry.trackId}</strong>
                <span className="by">{t?.artist}</span>
                <Specs track={t} />
                {entry.locked && <span className="stamp">{PIN_LABEL[entry.locked]}</span>}
              </div>
              <div className="sleeve-actions">
                <button className={`vote-pill ${mine ? 'cast' : ''}`} disabled={snapshot.frozen}
                  aria-pressed={mine} onClick={() => emit('queue.vote', { entryId: entry.entryId, up: !mine })}>
                  <b>{entry.votes}</b> {mine ? 'voted' : 'vote'}
                </button>
                {crew.isCrew && (
                  <span className="crew-tools">
                    <button className="text-btn" onClick={() => emit('queue.promote', { entryId: entry.entryId })}>play next</button>
                    <button className="text-btn" onClick={() => emit('queue.remove', { entryId: entry.entryId })}>pull</button>
                  </span>
                )}
              </div>
            </article>
          );
        })}
      </div>

      <form className="inline-form" onSubmit={add}>
        <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label="Record to add">
          <option value="">Dig a record from the shelves…</option>
          {list.filter((t) => !queued.has(t.trackId)).map((t) => (
            <option key={t.trackId} value={t.trackId}>
              {t.title} — {t.artist} · {t.acoustic.bpm} bpm · {t.acoustic.camelotKey}
            </option>
          ))}
        </select>
        <button className="btn ink" disabled={!choice || snapshot.frozen}>Add to crate</button>
      </form>
    </section>
  );
}
