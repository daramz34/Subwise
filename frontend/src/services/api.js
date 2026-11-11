// Central API client: base URL, auth header, one-shot token refresh, error shaping.
const BASE = import.meta.env.VITE_API_BASE || '/api/v1';
const KEY = 'subwise.refresh';

let access = null;      // access token lives in memory only
let refreshing = null;  // shared in-flight refresh (refresh tokens rotate: never refresh twice at once)
let onExpire = () => {};

export class ApiError extends Error {
  constructor(status, message, data) { super(message); this.status = status; this.data = data; }
}

const store = {
  get() { try { return localStorage.getItem(KEY); } catch { return null; } },
  set(v) { try { localStorage.setItem(KEY, v); } catch {} },
  del() { try { localStorage.removeItem(KEY); } catch {} },
};

export const setOnSessionExpired = (fn) => { onExpire = fn; };
export const hasStoredSession = () => !!store.get();
export const getRefreshToken = () => store.get();
export function setTokens(t) { access = t.access_token; store.set(t.refresh_token); }
export function clearTokens() { access = null; store.del(); }

function messageFrom(status, data) {
  const d = data && data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map((x) => {
      const f = (x.loc || []).filter((p) => p !== 'body').join('.');
      const m = String(x.msg).replace(/^Value error, /, '');
      return f ? `${f}: ${m}` : m;
    }).join('; ');
  }
  if (status === 429) return 'Too many attempts. Wait a minute and try again.';
  if (status >= 500) return 'The server had a problem. Try again in a moment.';
  return 'The request failed.';
}

// { fieldName: message } from a 422 response
export function fieldErrors(err) {
  const out = {};
  const d = err && err.data && err.data.detail;
  if (Array.isArray(d)) {
    for (const x of d) {
      const k = x.loc && x.loc[x.loc.length - 1];
      if (k) out[k] = String(x.msg).replace(/^Value error, /, '');
    }
  }
  return out;
}

async function send(path, { method = 'GET', body, form, auth = true, signal } = {}) {
  const headers = {};
  if (auth && access) headers.Authorization = `Bearer ${access}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  try {
    return await fetch(BASE + path, { method, headers, body: payload, signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Cannot reach the server. Check your connection.');
  }
}

async function readJson(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  try { return text ? JSON.parse(text) : null; } catch { return null; }
}

export function refreshSession() {
  if (refreshing) return refreshing;
  const token = store.get();
  if (!token) return Promise.resolve(false);
  refreshing = (async () => {
    try {
      const res = await send('/auth/refresh', { method: 'POST', body: { refresh_token: token }, auth: false });
      if (!res.ok) { clearTokens(); return false; }
      setTokens(await res.json());
      return true;
    } catch { return false; } finally { refreshing = null; }
  })();
  return refreshing;
}

export async function api(path, opts = {}) {
  let res = await send(path, opts);
  if (res.status === 401 && opts.auth !== false) {
    if (await refreshSession()) res = await send(path, opts);
    else onExpire();
  }
  const data = await readJson(res);
  if (!res.ok) throw new ApiError(res.status, messageFrom(res.status, data), data);
  return data;
}

export const http = {
  get: (p, o) => api(p, o),
  post: (p, body, o) => api(p, { ...o, method: 'POST', body }),
  put: (p, body, o) => api(p, { ...o, method: 'PUT', body }),
  patch: (p, body, o) => api(p, { ...o, method: 'PATCH', body }),
  del: (p, o) => api(p, { ...o, method: 'DELETE' }),
  upload: (p, form, o) => api(p, { ...o, method: 'POST', form }),
};
