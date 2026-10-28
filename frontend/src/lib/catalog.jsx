import { createContext, useContext, useEffect, useState } from 'react';
import { http } from './http.js';

const CatalogCtx = createContext({ byId: {}, list: [] });

export function CatalogProvider({ children, userKey }) {
  const [catalog, setCatalog] = useState({ byId: {}, list: [] });
  useEffect(() => {
    if (!userKey) return;
    http.get('/api/v1/tracks')
      .then((list) => setCatalog({ list, byId: Object.fromEntries(list.map((t) => [t.trackId, t])) }))
      .catch(() => {});
  }, [userKey]);
  return <CatalogCtx.Provider value={catalog}>{children}</CatalogCtx.Provider>;
}

export const useCatalog = () => useContext(CatalogCtx);

// Each track gets a stable sleeve colour derived from its id, so the same record always looks the same.
const SLEEVES = ['#e2553f', '#e8a93b', '#2f6f73', '#3b4f8c', '#8c3b6b', '#6b8c3b', '#c4683a', '#4a7fb0'];
export function sleeveColour(trackId = '') {
  let h = 0;
  for (const ch of trackId) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return SLEEVES[h % SLEEVES.length];
}

export function Specs({ track }) {
  if (!track) return null;
  const { bpm, camelotKey, energy } = track.acoustic;
  return (
    <span className="specs">
      <span>{bpm} bpm</span><span>{camelotKey}</span><span>nrg {Math.round(energy * 100)}</span>
    </span>
  );
}
