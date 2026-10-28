// Tiny History-API router: real paths (/booth/lg_123) instead of hash fragments.
import { useSyncExternalStore } from 'react';

const NAV_EVENT = 'dj-booth:navigate';

export function go(path) {
  if (path === location.pathname) return;
  history.pushState(null, '', path);
  window.dispatchEvent(new Event(NAV_EVENT));
  window.scrollTo(0, 0);
}

function subscribe(cb) {
  window.addEventListener('popstate', cb);
  window.addEventListener(NAV_EVENT, cb);
  return () => {
    window.removeEventListener('popstate', cb);
    window.removeEventListener(NAV_EVENT, cb);
  };
}

export function usePath() {
  return useSyncExternalStore(subscribe, () => location.pathname);
}

// Matches "/booth/:id" style patterns; returns params or null.
export function match(pattern, path) {
  const want = pattern.split('/').filter(Boolean);
  const have = path.split('/').filter(Boolean);
  if (want.length !== have.length) return null;
  const params = {};
  for (let i = 0; i < want.length; i += 1) {
    if (want[i].startsWith(':')) params[want[i].slice(1)] = decodeURIComponent(have[i]);
    else if (want[i] !== have[i]) return null;
  }
  return params;
}

export function Link({ to, children, ...rest }) {
  return (
    <a href={to} {...rest} onClick={(e) => {
      if (e.metaKey || e.ctrlKey || e.button !== 0) return;
      e.preventDefault();
      go(to);
    }}>{children}</a>
  );
}
