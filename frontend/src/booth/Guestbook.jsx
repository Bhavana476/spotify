import { useEffect, useRef, useState } from 'react';

const STAMPS = ['🔥', '❤️', '🙌', '💯', '🎉', '😂', '😴', '👎'];
const MOOD_MARK = { positive: '▲', neutral: '●', negative: '▼' };

function Entry({ entry }) {
  if (entry.msgType === 'ai_answer') {
    return (
      <li className="entry answer">
        <span className="asked">{entry.askedBy} asked “{entry.question}”</span>
        <p>{entry.body}</p>
        <span className="cite">
          {entry.sources?.length
            ? `from the liner notes: ${entry.sources.map((s) => `${s.id} (${s.type.replace('_', ' ')}, ${s.ts}s)`).join('; ')}`
            : 'nothing in the liner notes — the DJ declined to guess'}
        </span>
      </li>
    );
  }
  if (entry.msgType === 'system') return <li className="entry system">{entry.body}</li>;
  return (
    <li className={`entry mood-${entry.sentimentBucket}`}>
      <span className="mark" title={`${entry.sentimentBucket} energy (${entry.sentimentScore})`}>{MOOD_MARK[entry.sentimentBucket]}</span>
      <b>{entry.displayName}</b> {entry.body}
    </li>
  );
}

export default function Guestbook({ guestbook, writing, confetti, me, muted, emit }) {
  const [draft, setDraft] = useState('');
  const [askDj, setAskDj] = useState(false);
  const bottom = useRef(null);
  const lastTypingPing = useRef(0);

  useEffect(() => { bottom.current?.scrollIntoView({ block: 'nearest' }); }, [guestbook.length]);

  const scribblers = Object.entries(writing)
    .filter(([id, w]) => Number(id) !== me && Date.now() - w.at < 4000)
    .map(([, w]) => w.name);

  const submit = (e) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    if (askDj) emit('ai.ask', { question: text });
    else emit('chat.send', { body: text });
    emit('chat.typing', { typing: false });
    setDraft('');
  };

  return (
    <section className="panel guestbook">
      <header className="panel-head">
        <h3>Guestbook</h3>
        <span className="aside">▲ hyped · ● chill · ▼ flagging</span>
      </header>
      <ul className="entries">
        {guestbook.map((m) => <Entry key={m.messageId} entry={m} />)}
        <li ref={bottom} />
      </ul>
      <div className="confetti" aria-hidden="true">
        {confetti.map((c) => <span key={c.id} style={{ left: `${10 + c.x * 80}%` }}>{c.emoji}</span>)}
      </div>
      <p className="scribbling">{scribblers.length > 0 && `${scribblers.join(', ')} is writing…`}</p>
      <div className="stamps">
        {STAMPS.map((s) => <button key={s} className="stamp-btn" onClick={() => emit('chat.react', { emoji: s })}>{s}</button>)}
      </div>
      <form className="writer" onSubmit={submit}>
        <div className="toggle" role="radiogroup" aria-label="Message type">
          <button type="button" className={!askDj ? 'on' : ''} onClick={() => setAskDj(false)}>Sign</button>
          <button type="button" className={askDj ? 'on' : ''} onClick={() => setAskDj(true)}>Ask the DJ</button>
        </div>
        <input value={draft} maxLength={500} disabled={muted && !askDj}
          placeholder={askDj ? "Where's this sample from?" : muted ? 'The host has muted you' : 'Leave a line…'}
          onChange={(e) => {
            setDraft(e.target.value);
            if (Date.now() - lastTypingPing.current > 2000) {
              lastTypingPing.current = Date.now();
              emit('chat.typing', { typing: true });
            }
          }} />
        <button className="btn ink">{askDj ? 'Ask' : 'Sign'}</button>
      </form>
    </section>
  );
}
