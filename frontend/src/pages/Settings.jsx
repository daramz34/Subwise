import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';

export default function Settings() {
  const { user, logout } = useAuth();
  const { theme, set } = useTheme();
  return (
    <>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">Your account and how Subwise looks.</p>
      <dl className="facts">
        <dt>Name</dt><dd>{user.full_name}</dd>
        <dt>Email</dt><dd>{user.email}</dd>
        <dt>Main currency</dt><dd className="mono">{user.default_currency}</dd>
        <dt>Timezone</dt><dd className="mono">{user.timezone}</dd>
      </dl>
      <div className="seg" role="group" aria-label="Theme">
        <button aria-pressed={theme === 'dark'} onClick={() => set('dark')}>Dark</button>
        <button aria-pressed={theme === 'light'} onClick={() => set('light')}>Light</button>
      </div>
      <div><button className="btn" onClick={logout}>Sign out</button></div>
    </>
  );
}
