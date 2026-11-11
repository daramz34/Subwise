import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import Shell from './components/layout/Shell';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Subscriptions from './pages/Subscriptions';
import Settings from './pages/Settings';
import Upgrade from './pages/Upgrade';
import Intelligence from './pages/Intelligence';
import ImportCentre from './pages/ImportCentre';
import { Notifications } from './pages/Stubs';
const Splash = () => <div className="splash"><span className="wordmark">Subwise<i /></span></div>;

function Protected() {
  const { status } = useAuth();
  if (status === 'loading') return <Splash />;
  if (status === 'anon') return <Navigate to="/login" replace />;
  return <Shell />;
}

function Public({ children }) {
  const { status } = useAuth();
  if (status === 'loading') return <Splash />;
  if (status === 'authed') return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Public><Login /></Public>} />
      <Route path="/register" element={<Public><Register /></Public>} />
      <Route element={<Protected />}>
        <Route index element={<Dashboard />} />
        <Route path="subscriptions" element={<Subscriptions />} />
        <Route path="intelligence" element={<Intelligence />} />
        <Route path="import" element={<ImportCentre />} />
        <Route path="upgrade" element={<Upgrade />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}