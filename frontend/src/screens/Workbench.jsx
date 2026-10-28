import { useState } from 'react';
import { http } from '../lib/http.js';
import { useCatalog } from '../lib/catalog.jsx';

const KEYS = Array.from({ length: 12 }, (_, i) => [`${i + 1}A`, `${i + 1}B`]).flat();
const NOTE_TYPES = ['sample_credit', 'artist_bio', 'trivia', 'glossary'];
const BLANK = { trackId: '', title: '', artist: '', durationSeconds: 210, audioAssetUrl: '',
  acoustic: { bpm: 124, camelotKey: '8A', energy: 0.7, valence: 0.6 }, linerNotes: [] };

function toPayload(form) {
  return {
    trackId: form.trackId || null,
    title: form.title,
    artist: form.artist,
    durationSeconds: Number(form.durationSeconds),
    audioAssetUrl: form.audioAssetUrl || null,
    acoustic: { bpm: Number(form.acoustic.bpm), camelotKey: form.acoustic.camelotKey.trim(),
      energy: Number(form.acoustic.energy), valence: Number(form.acoustic.valence) },
    timeline: form.linerNotes.map((n) => ({ ts: Number(n.ts), type: n.type, text: n.text })),
  };
}

export default function Workbench() {
  const { list } = useCatalog();
  const [form, setForm] = useState(BLANK);
  const [verdict, setVerdict] = useState(null);

  async function loadTrack(id) {
    setVerdict(null);
    if (!id) return setForm(BLANK);
    const p = await http.get(`/api/v1/tracks/${id}/acoustic-profile`);
    setForm({ trackId: p.trackId, title: p.title, artist: p.artist, durationSeconds: p.durationSeconds, audioAssetUrl: '',
      acoustic: p.acoustic, linerNotes: p.timeline.map(({ ts, type, text }) => ({ ts, type, text })) });
  }

  async function submit(dryRun) {
    try {
      const res = dryRun
        ? await http.post('/api/v1/admin/tracks/validate', toPayload(form))
        : await http.put('/api/v1/admin/tracks', toPayload(form));
      setVerdict({ ok: true, text: dryRun ? 'Checks out — ready to file.' : `Filed as ${res.trackId}. Refresh to see it on the shelves.` });
    } catch (err) {
      setVerdict({ ok: false, text: err.message, fields: err.fieldErrors });
    }
  }

  const acoustic = (key) => (e) => setForm((f) => ({ ...f, acoustic: { ...f.acoustic, [key]: e.target.value } }));
  const note = (i, key) => (e) => setForm((f) => ({
    ...f, linerNotes: f.linerNotes.map((n, j) => (j === i ? { ...n, [key]: e.target.value } : n)),
  }));
  const badField = (name) => verdict?.fields?.some((f) => f.field === name);

  return (
    <article className="workbench">
      <header>
        <p className="kicker">Admin · record intake</p>
        <h1>The workbench</h1>
        <p className="quiet">File a record's acoustic profile and liner notes. Bad values are refused with the reason.</p>
      </header>

      <label>Re-file an existing record
        <select defaultValue="" onChange={(e) => loadTrack(e.target.value)}>
          <option value="">— a new record —</option>
          {list.map((t) => <option key={t.trackId} value={t.trackId}>{t.title} ({t.trackId})</option>)}
        </select>
      </label>

      <fieldset>
        <legend>The record</legend>
        <div className="quad">
          <label>Catalogue no.<input placeholder="t_7001" value={form.trackId} onChange={(e) => setForm({ ...form, trackId: e.target.value })} /></label>
          <label>Title<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
          <label>Artist<input value={form.artist} onChange={(e) => setForm({ ...form, artist: e.target.value })} /></label>
          <label>Length (s)<input type="number" value={form.durationSeconds} onChange={(e) => setForm({ ...form, durationSeconds: e.target.value })} /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>How it sounds</legend>
        <div className="quad">
          <label className={badField('acoustic.bpm') ? 'bad' : ''}>BPM<input type="number" step="0.1" value={form.acoustic.bpm} onChange={acoustic('bpm')} /></label>
          <label className={badField('acoustic.camelotKey') ? 'bad' : ''}>Camelot key
            <input list="camelot" value={form.acoustic.camelotKey} onChange={acoustic('camelotKey')} />
            <datalist id="camelot">{KEYS.map((k) => <option key={k} value={k} />)}</datalist>
          </label>
          <label className={badField('acoustic.energy') ? 'bad' : ''}>Energy 0–1<input type="number" step="0.01" value={form.acoustic.energy} onChange={acoustic('energy')} /></label>
          <label className={badField('acoustic.valence') ? 'bad' : ''}>Valence 0–1<input type="number" step="0.01" value={form.acoustic.valence} onChange={acoustic('valence')} /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Liner notes (what the DJ is allowed to say)</legend>
        {form.linerNotes.map((n, i) => (
          <div key={i} className="note-row">
            <input type="number" className="ts" value={n.ts} onChange={note(i, 'ts')} aria-label="seconds" />
            <select value={n.type} onChange={note(i, 'type')}>{NOTE_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
            <input value={n.text} onChange={note(i, 'text')} aria-label="note text" />
            <button type="button" className="text-btn danger"
              onClick={() => setForm({ ...form, linerNotes: form.linerNotes.filter((_, j) => j !== i) })}>remove</button>
          </div>
        ))}
        <button type="button" className="text-btn"
          onClick={() => setForm({ ...form, linerNotes: [...form.linerNotes, { ts: 0, type: 'trivia', text: '' }] })}>+ add a note</button>
      </fieldset>

      {verdict && (
        <div className={`notice ${verdict.ok ? 'good' : 'bad'}`} role="status">
          {verdict.fields?.length
            ? verdict.fields.map((f, i) => <div key={i}><b>{f.field}</b> — {f.message}</div>)
            : verdict.text}
        </div>
      )}
      <div className="row-gap">
        <button className="btn" onClick={() => submit(true)}>Check it</button>
        <button className="btn ink" onClick={() => submit(false)}>File the record</button>
      </div>
    </article>
  );
}
