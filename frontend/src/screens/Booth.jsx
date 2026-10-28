import { Link } from '../lib/nav.jsx';
import { useRoom } from '../lib/room.js';
import Turntable from '../booth/Turntable.jsx';
import Crate from '../booth/Crate.jsx';
import Clash from '../booth/Clash.jsx';
import Notes from '../booth/Notes.jsx';
import Guestbook from '../booth/Guestbook.jsx';
import Crowd from '../booth/Crowd.jsx';
import MoodGauge from '../booth/MoodGauge.jsx';

const LINK_TEXT = { connecting: 'tuning in', live: 'on air', rejoining: 'reconnecting…' };

// Lounge authority is per lounge: admin is global, host/co-DJ come from the room itself.
function crewFor(snapshot, user) {
  const role = user.role === 'admin' ? 'admin'
    : snapshot.hostUserId === user.userId ? 'host'
      : snapshot.coDjIds.includes(user.userId) ? 'co_dj' : 'listener';
  return { role, isCrew: role !== 'listener', isHost: role === 'host' || role === 'admin' };
}

export default function Booth({ loungeId, user }) {
  const [room, emit] = useRoom(loungeId);
  const { snapshot } = room;

  if (room.link === 'ended') {
    return <div className="closed-sign"><h2>Lights up — this night is over.</h2><Link to={`/ledger/${loungeId}`}>Read the ledger →</Link></div>;
  }
  if (room.link === 'refused') {
    return <div className="closed-sign"><h2>The door's shut for you.</h2><p>The booth is locked, full, you were removed, or it doesn't exist.</p><Link to="/">Back to the shop</Link></div>;
  }
  if (!snapshot) return <div className="closed-sign"><h2>Tuning in…</h2></div>;

  const crew = crewFor(snapshot, user);
  const me = snapshot.participants.find((p) => p.userId === user.userId);

  return (
    <div className="booth">
      <div className="marquee">
        <div>
          <p className="kicker">{LINK_TEXT[room.link] ?? room.link}{room.rttMs != null && ` · ${room.rttMs} ms`}</p>
          <h1>{snapshot.settings.vibeProfile}</h1>
          <p className="marquee-sub">
            Invite <button className="code-chip" title="Copy invite code"
              onClick={() => navigator.clipboard?.writeText(snapshot.settings.inviteCode)}>{snapshot.settings.inviteCode}</button>
            {' '}· you're the <b>{crew.role.replace('_', '-')}</b>
          </p>
        </div>
        <MoodGauge mood={room.mood} />
        {crew.isHost && (
          <div className="host-switches">
            <button className="btn" onClick={() => emit('mod.lock', { locked: !snapshot.locked })}>
              {snapshot.locked ? 'Unlock the door' : 'Lock the door'}</button>
            <button className="btn danger" onClick={() => window.confirm('Call last orders and end the night for everyone?') && emit('lounge.end')}>
              End the night</button>
          </div>
        )}
      </div>

      {snapshot.frozen && <div className="notice">The host stepped out — the crate is frozen until they're back.</div>}
      {room.problem && <div className="notice bad" role="alert">{room.problem}</div>}

      <Turntable snapshot={snapshot} crew={crew} emit={emit} />

      <div className="booth-floor">
        <div className="stack wide">
          <Crate snapshot={snapshot} me={user.userId} crew={crew} emit={emit} />
          <div className="duo">
            <Clash snapshot={snapshot} crew={crew} emit={emit} />
            <Notes snapshot={snapshot} notes={room.notes} crew={crew} emit={emit} />
          </div>
        </div>
        <div className="stack">
          <Guestbook guestbook={room.guestbook} writing={room.writing} confetti={room.confetti}
            me={user.userId} muted={me?.muted} emit={emit} />
          <Crowd snapshot={snapshot} me={user.userId} crew={crew} emit={emit} />
        </div>
      </div>
    </div>
  );
}
