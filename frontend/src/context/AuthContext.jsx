import { createContext, useContext, useEffect, useState } from 'react';
import * as svc from '../services/auth';
import { hasStoredSession, refreshSession, setOnSessionExpired } from '../services/api';

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | authed | anon

  useEffect(() => {
    setOnSessionExpired(() => { setUser(null); setStatus('anon'); });
    (async () => {
      if (!hasStoredSession() || !(await refreshSession())) return setStatus('anon');
      try { setUser(await svc.me()); setStatus('authed'); } catch { setStatus('anon'); }
    })();
  }, []);

  const signIn = (fn) => async (...args) => {
    const u = await fn(...args);
    setUser(u); setStatus('authed');
    return u;
  };
  const login = signIn(svc.login);
  const register = signIn(svc.register);
  const logout = async () => { await svc.logout(); setUser(null); setStatus('anon'); };

  return <Ctx.Provider value={{ user, status, login, register, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
