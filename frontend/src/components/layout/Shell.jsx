import { Link, NavLink, Outlet } from 'react-router-dom';
import { Bell, Home, List, Moon, Settings, Sparkles, Sun, Upload, Zap } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';

const MAIN = [
  { to: '/', label: 'Overview', short: 'Overview', Icon: Home },
  { to: '/subscriptions', label: 'Subscriptions', short: 'Subs', Icon: List },
  { to: '/intelligence', label: 'AI Intelligence', short: 'Ask AI', Icon: Sparkles },
  { to: '/import', label: 'Import', short: 'Import', Icon: Upload },
  { to: '/upgrade', label: 'Upgrade', short: 'Plus', Icon: Zap },
];

const Item = ({ to, label, Icon }) => (
  <NavLink to={to} end={to === '/'}><Icon size={18} aria-hidden="true" />{label}</NavLink>
);

export default function Shell() {
  const { theme, toggle } = useTheme();
  const next = theme === 'dark' ? 'light' : 'dark';
  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="side">
        <Link to="/" className="wordmark">Subwise<i /></Link>
        <nav className="nav grow" aria-label="Main">
          {MAIN.map((m) => <Item key={m.to} {...m} />)}
        </nav>
        <div className="nav">
          <Item to="/notifications" label="Notifications" Icon={Bell} />
          <Item to="/settings" label="Settings" Icon={Settings} />
          <button className="navbtn" onClick={toggle}>
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />} Use {next} theme
          </button>
        </div>
      </aside>
      <header className="topbar">
        <Link to="/" className="wordmark">Subwise<i /></Link>
        <div className="nav">
          <NavLink to="/notifications" aria-label="Notifications"><Bell size={20} /></NavLink>
          <NavLink to="/settings" aria-label="Settings"><Settings size={20} /></NavLink>
          <button className="navbtn" onClick={toggle} aria-label={`Use ${next} theme`}>
            {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>
      </header>
      <main className="main" id="main"><Outlet /></main>
      <nav className="tabs" aria-label="Main">
        {MAIN.map(({ to, short, Icon }) => (
          <NavLink key={to} to={to} end={to === '/'}><Icon size={20} aria-hidden="true" />{short}</NavLink>
        ))}
      </nav>
    </div>
  );
}
