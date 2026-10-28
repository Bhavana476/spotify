// Live lounge connection. All socket traffic flows through one reducer, so every screen element reads from a
// single, versioned room object (older snapshots are ignored; a resync replaces everything).
import { useEffect, useReducer, useRef } from 'react';
import { session } from './http.js';

const initial = {
  link: 'connecting', snapshot: null, version: -1, guestbook: [], notes: [], mood: null,
  writing: {}, confetti: [], problem: null, rttMs: null,
};

function reducer(room, action) {
  switch (action.type) {
    case 'link': return { ...room, link: action.link };
    case 'resync':
      return { ...room, snapshot: action.snapshot, version: action.version, guestbook: action.snapshot.chatHistory ?? [],
        notes: action.snapshot.aiFeed ?? [], mood: action.snapshot.sentiment ?? room.mood, problem: null };
    case 'snapshot':
      if (action.version < room.version) return room;
      return { ...room, snapshot: action.snapshot, version: action.version, mood: action.snapshot.sentiment ?? room.mood };
    case 'people':
      return room.snapshot ? { ...room, snapshot: { ...room.snapshot, participants: action.people } } : room;
    case 'entry': return { ...room, guestbook: [...room.guestbook.slice(-199), action.entry] };
    case 'note': return { ...room, notes: [...room.notes.slice(-29), action.note] };
    case 'mood': return { ...room, mood: action.mood };
    case 'writing': {
      const writing = { ...room.writing };
      if (action.on) writing[action.userId] = { name: action.name, at: Date.now() };
      else delete writing[action.userId];
      return { ...room, writing };
    }
    case 'confetti': return { ...room, confetti: [...room.confetti.slice(-9), action.burst] };
    case 'problem': return { ...room, problem: action.message };
    case 'rtt': return { ...room, rttMs: action.rttMs };
    default: return room;
  }
}

const TERMINAL = { 4000: 'ended', 4410: 'ended', 4401: 'refused', 4403: 'refused', 4404: 'refused' };

export function useRoom(loungeId) {
  const [room, dispatch] = useReducer(reducer, initial);
  const socket = useRef(null);
  const lastRtt = useRef(null);

  const emit = (event, payload = {}) => {
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ event, payload, requestId: crypto.randomUUID() }));
  };

  useEffect(() => {
    let stopped = false;
    let attempt = 0;
    const timers = [];

    const handle = ({ event, payload, version }) => {
      switch (event) {
        case 'lounge.sync.state': dispatch({ type: 'resync', snapshot: payload, version }); break;
        case 'lounge.queue.update': dispatch({ type: 'snapshot', snapshot: payload, version }); break;
        case 'lounge.presence.list': dispatch({ type: 'people', people: payload.participants }); break;
        case 'lounge.chat.message': dispatch({ type: 'entry', entry: payload }); break;
        case 'lounge.ai.dj_announcement': dispatch({ type: 'note', note: payload }); break;
        case 'lounge.sentiment.score': dispatch({ type: 'mood', mood: payload }); break;
        case 'lounge.chat.typing':
          dispatch({ type: 'writing', userId: payload.userId, name: payload.displayName, on: payload.typing }); break;
        case 'lounge.chat.reaction':
          dispatch({ type: 'confetti', burst: { id: crypto.randomUUID(), emoji: payload.emoji, x: Math.random() } }); break;
        case 'lounge.sync.pong': {
          lastRtt.current = Math.round(performance.now() - payload.clientSentAt);
          dispatch({ type: 'rtt', rttMs: lastRtt.current });
          break;
        }
        case 'lounge.error':
          dispatch({ type: 'problem', message: payload.message });
          timers.push(setTimeout(() => dispatch({ type: 'problem', message: null }), 4500));
          break;
        case 'lounge.removed': stopped = true; dispatch({ type: 'link', link: 'refused' }); break;
        default: break;
      }
    };

    const open = async () => {
      const token = await session.token();
      if (!token || stopped) return;
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${scheme}://${location.host}/ws/lounges/${loungeId}?token=${encodeURIComponent(token)}`);
      socket.current = ws;
      dispatch({ type: 'link', link: attempt ? 'rejoining' : 'connecting' });
      let ping;
      let renew;
      ws.onopen = () => {
        attempt = 0;
        dispatch({ type: 'link', link: 'live' });
        const sendPing = () => emit('sync.ping', { clientSentAt: performance.now(), lastRttMs: lastRtt.current });
        sendPing();
        ping = setInterval(sendPing, 5000);
        renew = setInterval(async () => emit('auth.renew', { token: await session.token() }), 600_000);
      };
      ws.onmessage = (e) => handle(JSON.parse(e.data));
      ws.onclose = (e) => {
        clearInterval(ping);
        clearInterval(renew);
        if (stopped) return;
        if (TERMINAL[e.code]) { dispatch({ type: 'link', link: TERMINAL[e.code] }); return; }
        dispatch({ type: 'link', link: 'rejoining' });
        timers.push(setTimeout(open, Math.min(8000, 400 * 2 ** attempt++)));
      };
    };

    open();
    return () => {
      stopped = true;
      timers.forEach(clearTimeout);
      socket.current?.close();
    };
  }, [loungeId]);

  return [room, emit];
}
