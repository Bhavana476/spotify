// Session + REST access. One Session object owns tokens; listeners are told when it changes.
const STORE = 'dj-booth/session/v2';

class Session {
  #data = null;
  #listeners = new Set();
  #refreshing = null;

  constructor() {
    try { this.#data = JSON.parse(sessionStorage.getItem(STORE)); } catch { this.#data = null; }
  }

  get user() { return this.#data?.user ?? null; }
  get signedIn() { return Boolean(this.#data); }

  subscribe(fn) { this.#listeners.add(fn); return () => this.#listeners.delete(fn); }

  save(data) {
    this.#data = data;
    if (data) sessionStorage.setItem(STORE, JSON.stringify(data));
    else sessionStorage.removeItem(STORE);
    this.#listeners.forEach((fn) => fn(data));
  }

  #expiresAt(token) {
    try {
      const body = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
      return JSON.parse(atob(body)).exp * 1000;
    } catch { return 0; }
  }

  // Returns a token valid for at least another minute, rotating the refresh token if needed.
  async token() {
    if (!this.#data) return null;
    if (this.#expiresAt(this.#data.accessToken) - Date.now() > 60_000) return this.#data.accessToken;
    if (!this.#refreshing) {
      this.#refreshing = fetch('/api/v1/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken: this.#data.refreshToken }),
      })
        .then(async (res) => {
          if (!res.ok) { this.save(null); return null; }
          const fresh = await res.json();
          this.save(fresh);
          return fresh.accessToken;
        })
        .finally(() => { this.#refreshing = null; });
    }
    return this.#refreshing;
  }

  async signOut() {
    const refreshToken = this.#data?.refreshToken;
    this.save(null);
    if (refreshToken) {
      fetch('/api/v1/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken }) }).catch(() => {});
    }
  }
}

export const session = new Session();

export class RequestFailed extends Error {
  constructor(status, payload) {
    const fieldErrors = payload?.errors?.map((e) => (e.field ? `${e.field} — ${e.message}` : e.message));
    super(fieldErrors?.join(' · ') || payload?.detail || `Request failed (${status})`);
    this.status = status;
    this.fieldErrors = payload?.errors ?? [];
  }
}

async function call(method, path, body, { anonymous = false } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (!anonymous) {
    const t = await session.token();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && !anonymous) session.save(null);
    throw new RequestFailed(res.status, payload);
  }
  return payload;
}

export const http = {
  get: (path) => call('GET', path),
  post: (path, body, opts) => call('POST', path, body ?? {}, opts),
  put: (path, body) => call('PUT', path, body),
};
