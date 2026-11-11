import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '../components/forms/AuthLayout';
import Field from '../components/forms/Field';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setError(''); setBusy(true);
    try {
      await login(email, password);
      nav('/', { replace: true });
    } catch (err) {
      setError(err.status === 401 ? 'Email or password is incorrect.' : err.message);
    } finally { setBusy(false); }
  }

  return (
    <AuthLayout title="Sign in" footer={<>New here? <Link to="/register">Create an account</Link></>}>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert" role="alert">{error}</div>}
        <Field label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Field label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button className="btn btn-primary btn-block" disabled={busy || !email || !password}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </AuthLayout>
  );
}
