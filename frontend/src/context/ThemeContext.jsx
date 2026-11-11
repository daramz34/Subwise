import { createContext, useCallback, useContext, useState } from 'react';

const Ctx = createContext(null);

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark');
  const set = useCallback((t) => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('subwise.theme', t); } catch {}
    setTheme(t);
  }, []);
  const toggle = () => set(theme === 'dark' ? 'light' : 'dark');
  return <Ctx.Provider value={{ theme, set, toggle }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
