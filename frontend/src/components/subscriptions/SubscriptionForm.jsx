import { useState } from 'react';
import { Link } from 'react-router-dom';
import Field from '../forms/Field';
import { createSubscription, updateSubscription } from '../../services/subscriptions';
import { fieldErrors } from '../../services/api';

const INTERVALS = [
  { value: 'month', label: 'Monthly' }, { value: 'year', label: 'Yearly' },
  { value: 'week', label: 'Weekly' }, { value: 'day', label: 'Daily' },
];
const STATUSES = [
  { value: 'active', label: 'Active' }, { value: 'trial', label: 'Free trial' },
  { value: 'paused', label: 'Paused' }, { value: 'cancelled', label: 'Cancelled' },
];

const blank = (cur) => ({
  name: '', amount: '', currency: cur || 'USD', billing_interval: 'month', next_renewal_date: '',
  interval_count: '1', status: 'active', trial_end_date: '', category_id: '', website_url: '',
  notes: '', is_shared: false, my_share_percent: '100',
});

const fromSub = (s) => ({
  name: s.name, amount: s.amount, currency: s.currency, billing_interval: s.billing_interval,
  next_renewal_date: s.next_renewal_date || '', interval_count: String(s.interval_count),
  status: s.status, trial_end_date: s.trial_end_date || '', category_id: s.category_id || '',
  website_url: s.website_url || '', notes: s.notes || '', is_shared: s.is_shared,
  my_share_percent: String(s.my_share_percent),
});

function validate(f) {
  const e = {};
  if (!f.name.trim()) e.name = 'Enter a name.';
  if (!/^\d+(\.\d{1,2})?$/.test(f.amount.trim())) e.amount = 'Use a number with up to 2 decimals.';
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) e.currency = 'Use a 3-letter code, like USD.';
  if (f.status === 'trial' && !f.trial_end_date) e.trial_end_date = 'A trial needs an end date.';
  if (f.is_shared && !(Number(f.my_share_percent) > 0 && Number(f.my_share_percent) <= 100)) e.my_share_percent = 'Enter 1 to 100.';
  return e;
}

export default function SubscriptionForm({ initial, categories, defaultCurrency, onSaved, onClose }) {
  const editing = !!initial;
  const [f, setF] = useState(editing ? fromSub(initial) : blank(defaultCurrency));
  const [errors, setErrors] = useState({});
  const [error, setError] = useState('');
  const [limit, setLimit] = useState('');
  const [dup, setDup] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  function payload() {
    const body = {
      name: f.name.trim(), amount: f.amount.trim(), currency: f.currency.trim().toUpperCase(),
      billing_interval: f.billing_interval, interval_count: Number(f.interval_count) || 1,
      status: f.status, is_shared: f.is_shared, my_share_percent: f.is_shared ? f.my_share_percent : '100',
    };
    const opt = (k, v) => { if (v !== '') body[k] = v; else if (editing) body[k] = null; };
    opt('next_renewal_date', f.next_renewal_date);
    opt('trial_end_date', f.status === 'trial' ? f.trial_end_date : '');
    opt('category_id', f.category_id);
    opt('website_url', f.website_url.trim());
    opt('notes', f.notes.trim());
    return body;
  }

  async function save(acknowledge = false) {
    setError(''); setLimit(''); setBusy(true);
    try {
      const body = payload();
      if (editing) await updateSubscription(initial.id, body);
      else await createSubscription(acknowledge ? { ...body, acknowledge_duplicate: true } : body);
      onSaved();
    } catch (err) {
      if (!editing && err.status === 409 && err.data && err.data.similar_subscription_ids) setDup(true);
      else if (err.status === 403) setLimit(err.message);
      else {
        const fe = fieldErrors(err);
        if (Object.keys(fe).length) setErrors(fe);
        else setError(err.message);
      }
    } finally { setBusy(false); }
  }

  function submit(e) {
    e.preventDefault();
    const v = validate(f);
    setErrors(v);
    if (Object.keys(v).length) return;
    save(false);
  }

  return (
    <form onSubmit={submit} noValidate>
      {error && <div className="alert" role="alert">{error}</div>}
      {limit && (
        <div className="notice" role="alert">
          {limit} <Link to="/upgrade" onClick={onClose}>See the Plus plan</Link>
        </div>
      )}
      <Field label="Name" value={f.name} onChange={set('name')} error={errors.name} placeholder="Netflix" autoFocus />
      <div className="row2">
        <Field label="Amount" inputMode="decimal" value={f.amount} onChange={set('amount')} error={errors.amount} placeholder="15.49" />
        <Field label="Currency" value={f.currency} onChange={set('currency')} error={errors.currency} maxLength={3} />
      </div>
      <div className="row2">
        <Field label="Billed" options={INTERVALS} value={f.billing_interval} onChange={set('billing_interval')} />
        <Field label="Next renewal" type="date" value={f.next_renewal_date} onChange={set('next_renewal_date')} error={errors.next_renewal_date} />
      </div>

      <details className="adv">
        <summary>More details</summary>
        <div className="row2">
          <Field label="Status" options={STATUSES} value={f.status} onChange={set('status')} />
          <Field label="Repeat every" type="number" min="1" max="36" value={f.interval_count} onChange={set('interval_count')} hint="Monthly and 3 means quarterly." />
        </div>
        {f.status === 'trial' && (
          <Field label="Trial ends" type="date" value={f.trial_end_date} onChange={set('trial_end_date')} error={errors.trial_end_date} />
        )}
        <Field label="Category" options={[{ value: '', label: 'No category' }, ...categories.map((c) => ({ value: c.id, label: c.name }))]} value={f.category_id} onChange={set('category_id')} error={errors.category_id} />
        <Field label="Website" type="url" value={f.website_url} onChange={set('website_url')} error={errors.website_url} placeholder="https://" />
        <Field label="Notes" value={f.notes} onChange={set('notes')} error={errors.notes} />
        <label className="check">
          <input type="checkbox" checked={f.is_shared} onChange={(e) => setF({ ...f, is_shared: e.target.checked })} />
          I split this cost with someone
        </label>
        {f.is_shared && <Field label="My share (%)" inputMode="decimal" value={f.my_share_percent} onChange={set('my_share_percent')} error={errors.my_share_percent} />}
      </details>

      {dup ? (
        <div className="notice" role="alert">
          <p style={{ marginBottom: 12 }}>You already track something similar. Save this one anyway?</p>
          <div className="form-actions">
            <button type="button" className="btn" onClick={() => setDup(false)} disabled={busy}>Go back</button>
            <button type="button" className="btn btn-primary" onClick={() => save(true)} disabled={busy}>{busy ? 'Saving…' : 'Save anyway'}</button>
          </div>
        </div>
      ) : (
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : editing ? 'Save changes' : 'Add subscription'}</button>
        </div>
      )}
    </form>
  );
}
