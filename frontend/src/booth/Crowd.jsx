const ROLE_NAME = { listener: 'guest', co_dj: 'co-DJ', host: 'host', admin: 'admin' };

function signal(rtt) {
  if (rtt == null) return { bars: 0, label: 'measuring' };
  if (rtt < 80) return { bars: 3, label: `${rtt} ms` };
  if (rtt < 250) return { bars: 2, label: `${rtt} ms` };
  return { bars: 1, label: `${rtt} ms` };
}

export default function Crowd({ snapshot, me, crew, emit }) {
  return (
    <section className="panel crowd">
      <header className="panel-head">
        <h3>On the floor</h3>
        <span className="aside">{snapshot.participants.length} here</span>
      </header>
      <ul className="people">
        {snapshot.participants.map((p) => {
          const s = signal(p.rttMs);
          const manageable = crew.isHost && p.userId !== snapshot.hostUserId && p.userId !== me;
          return (
            <li key={p.userId}>
              <span className="signal" title={`connection ${s.label}`}>
                {[1, 2, 3].map((b) => <i key={b} className={b <= s.bars ? 'lit' : ''} />)}
              </span>
              <span className="who">{p.displayName}{p.userId === me && ' (you)'}</span>
              <span className={`badge badge-${p.role}`}>{ROLE_NAME[p.role]}</span>
              {p.muted && <span className="badge muted-badge">muted</span>}
              {manageable && (
                <details className="manage">
                  <summary>manage</summary>
                  <div>
                    <button className="text-btn" onClick={() => emit(p.muted ? 'mod.unmute' : 'mod.mute', { userId: p.userId })}>{p.muted ? 'unmute' : 'mute'}</button>
                    <button className="text-btn" onClick={() => emit('mod.set_role', { userId: p.userId, role: p.role === 'co_dj' ? 'listener' : 'co_dj' })}>
                      {p.role === 'co_dj' ? 'make guest' : 'make co-DJ'}</button>
                    <button className="text-btn" onClick={() => window.confirm(`Hand the booth to ${p.displayName}?`) && emit('mod.transfer_host', { userId: p.userId })}>hand over booth</button>
                    <button className="text-btn danger" onClick={() => window.confirm(`Show ${p.displayName} the door?`) && emit('mod.remove', { userId: p.userId })}>remove</button>
                  </div>
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
