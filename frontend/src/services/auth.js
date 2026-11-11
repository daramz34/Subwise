import { api, setTokens, clearTokens, getRefreshToken } from './api';

export const me = () => api('/auth/me');

export async function login(email, password) {
  const t = await api('/auth/login', { method: 'POST', body: { email, password }, auth: false });
  setTokens(t);
  return me();
}

export async function register(data) {
  await api('/auth/register', { method: 'POST', body: data, auth: false });
  return login(data.email, data.password);
}

export async function logout() {
  const refresh_token = getRefreshToken();
  if (refresh_token) {
    try { await api('/auth/logout', { method: 'POST', body: { refresh_token }, auth: false }); } catch {}
  }
  clearTokens();
}
