import { useState } from 'react';
import { http, session } from '../lib/http.js';

export default function Door() {
  const [newcomer, setNewcomer] = useState(false);
  const [fields, setFields] = useState({ email: '', password: '', displayName: '' });
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);

  const update = (key) => (e) => setFields((f) => ({ ...f, [key]: e.target.value }));

  async function enter(e) {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const body = newcomer ? fields : { email: fields.email, password: fields.password };
      session.save(await http.post(`/api/v1/auth/${newcomer ? 'register' : 'login'}`, body, { anonymous: true }));
    } catch (err) {
      setProblem(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="door">
      <aside className="door-poster">
        <p className="kicker">Est. 2026 · open late</p>
        <h1>The<br />Listening<br />Room</h1>
        <p>A record shop where the crowd votes the crate, records battle for the next spot, and an AI selector
          only ever mixes in key.</p>
        <div className="poster-record" aria-hidden="true" />
      </aside>

      <form className="door-form" onSubmit={enter}>
        <h2>{newcomer ? 'Get a membership card' : 'Show your card'}</h2>
        {newcomer && (
          <label>What should the room call you?
            <input value={fields.displayName} onChange={update('displayName')} minLength={2} required />
          </label>
        )}
        <label>Email
          <input type="email" value={fields.email} onChange={update('email')} autoComplete="username" required />
        </label>
        <label>Password
          <input type="password" value={fields.password} onChange={update('password')} required
            minLength={newcomer ? 8 : 1} autoComplete={newcomer ? 'new-password' : 'current-password'} />
        </label>
        {problem && <p className="problem">{problem}</p>}
        <button className="btn ink big" disabled={busy}>{newcomer ? 'Join the shop' : 'Walk in'}</button>
        <button type="button" className="text-btn" onClick={() => setNewcomer((v) => !v)}>
          {newcomer ? 'Already a member? Sign in' : 'First visit? Get a card'}
        </button>
        <p className="fineprint">Demo cards after seeding: admin, host, codj, listener, guest @djstudio.dev</p>
      </form>
    </div>
  );
}
