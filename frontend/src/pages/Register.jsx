import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import AuthLayout from '../components/forms/AuthLayout';
import Field from '../components/forms/Field';
import { useAuth } from '../context/AuthContext';
import { fieldErrors } from '../services/api';

const CURRENCIES = ['USD', 'NGN', 'EUR', 'GBP', 'CAD', 'AUD', 'GHS', 'KES', 'ZAR', 'INR'];

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ full_name: '', email: '', password: '', default_currency: 'USD' });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setError(''); setErrors({});
    if (f.password.length < 8 || !/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) {
      return setErrors({ password: 'Use at least 8 characters with a letter and a number.' });
    }
    setBusy(true);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      await register({ ...f, timezone });
      nav('/', { replace: true });
    } catch (err) {
      const fe = fieldErrors(err);
      if (Object.keys(fe).length) setErrors(fe); else setError(err.message);
    } finally { setBusy(false); }
  }

  return (
    <AuthLayout title="Create your account" footer={<>Already registered? <Link to="/login">Sign in</Link></>}>
      <form onSubmit={submit} noValidate>
        {error && <div className="alert" role="alert">{error}</div>}
        <Field label="Full name" autoComplete="name" value={f.full_name} onChange={set('full_name')} error={errors.full_name} required />
        <Field label="Email" type="email" autoComplete="email" value={f.email} onChange={set('email')} error={errors.email} required />
        <Field label="Password" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} error={errors.password} hint="8+ characters, with a letter and a number." required />
        <Field label="Main currency" options={CURRENCIES} value={f.default_currency} onChange={set('default_currency')} error={errors.default_currency} />
        <button className="btn btn-primary btn-block" disabled={busy || !f.full_name || !f.email || !f.password}>{busy ? 'Creating account…' : 'Create account'}</button>
      </form>
    </AuthLayout>
  );
}
