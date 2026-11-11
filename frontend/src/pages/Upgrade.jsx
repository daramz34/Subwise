import { useCallback, useEffect, useState } from 'react';
import '../styles/upgrade.css';
import { captureOrder, createOrder, getEntitlement, getOrders, getPlans } from '../services/payments';
import { takePaypalReturn } from '../services/paypalReturn';
import { money } from '../utils/format';

const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '');

function features(plan) {
  const l = (plan && plan.limits) || {};
  return [
    ['Subscriptions', l.max_subscriptions ? `Up to ${l.max_subscriptions}` : 'Unlimited'],
    ['Imports', l.imports_per_month ? `${l.imports_per_month} a month` : 'Unlimited'],
    ['AI analyst', l.ai_chat ? 'Included' : null],
  ];
}

function Plan({ plan, plus, children }) {
  const free = Number(plan.price) === 0;
  return (
    <section className={`plan${plus ? ' plan-plus' : ''}`}>
      <h2>{plus ? 'Plus' : 'Free'}</h2>
      <p className="price mono">
        {free ? 'No cost' : `${money(plan.price, plan.currency)}${plan.duration_days ? ` for ${plan.duration_days} days` : ''}`}
      </p>
      <ul className="feat">
        {features(plan).map(([k, v]) => (
          <li key={k} className={v ? '' : 'off'}><span>{k}</span><span className="mono">{v || 'Not included'}</span></li>
        ))}
      </ul>
      {children}
    </section>
  );
}

export default function Upgrade() {
  const [plans, setPlans] = useState([]);
  const [ent, setEnt] = useState(null);
  const [orders, setOrders] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [ret, setRet] = useState(null); // { phase: confirming | done | cancelled | error, message, token }

  const refresh = useCallback(async () => {
    const [e, o] = await Promise.allSettled([getEntitlement(), getOrders()]);
    if (e.status === 'fulfilled') setEnt(e.value);
    if (o.status === 'fulfilled' && Array.isArray(o.value)) setOrders(o.value);
  }, []);

  const capture = useCallback(async (token) => {
    setRet({ phase: 'confirming' });
    try {
      const r = await captureOrder(token);
      if (r && r.status === 'completed') setRet({ phase: 'done' });
      else setRet({ phase: 'error', token, message: `PayPal reports the payment as "${(r && r.status) || 'unknown'}". Plus is not active yet.` });
    } catch (e) {
      setRet({ phase: 'error', token, message: e.message });
    }
    refresh();
  }, [refresh]);

  useEffect(() => {
    getPlans().then((p) => setPlans(Array.isArray(p) ? p : [])).catch((e) => setLoadError(e.message));
    refresh();
    const back = takePaypalReturn();
    if (back && back.result === 'return' && back.token) capture(back.token);
    else if (back && back.result === 'cancel') setRet({ phase: 'cancelled' });
  }, [refresh, capture]);

  async function upgrade() {
    setError(''); setBusy(true);
    try {
      const o = await createOrder();
      const url = o && (o.approve_url || o.approval_url);
      if (!url) throw new Error('PayPal did not return a checkout link.');
      window.location.assign(url);
    } catch (e) { setError(e.message); setBusy(false); }
  }

  const code = (ent && (ent.plan_code || (ent.plan && ent.plan.code))) || 'free';
  const isPlus = code === 'plus' && (!ent.status || ent.status === 'active');
  const free = plans.find((p) => p.code === 'free');
  const plus = plans.find((p) => p.code === 'plus');
  const history = orders.filter((o) => o.status !== 'created');

  return (
    <>
      <h1 className="page-title">Free and Plus.</h1>
      <p className="page-sub">Free covers the basics. Plus removes the limits and adds the AI analyst.</p>
      <p className="sandbox" role="note">
        Test mode. Checkout runs on PayPal Sandbox, so no real money moves. Pay with a sandbox test buyer account, not your own PayPal login.
      </p>

      {ret && ret.phase === 'confirming' && <div className="ok" role="status">Confirming your payment with PayPal…</div>}
      {ret && ret.phase === 'done' && <div className="ok" role="status">Payment confirmed. Plus is now active on your account.</div>}
      {ret && ret.phase === 'cancelled' && <div className="ok" role="status">Checkout was cancelled. Nothing was charged.</div>}
      {ret && ret.phase === 'error' && (
        <div className="alert" role="alert">
          {ret.message}
          {ret.token && <> <button className="btn" onClick={() => capture(ret.token)}>Check again</button></>}
        </div>
      )}
      {loadError && <div className="alert" role="alert">{loadError}</div>}
      {error && <div className="alert" role="alert">{error}</div>}

      <p className="yourplan">
        Your plan: <strong>{isPlus ? 'Plus' : 'Free'}</strong>
        {isPlus && ent.expires_at ? `, active until ${day(ent.expires_at)}` : ''}
      </p>

      {free && plus && (
        <div className="plans">
          <Plan plan={free}>{!isPlus && <p className="mono" style={{ color: 'var(--text-2)' }}>Your current plan</p>}</Plan>
          <Plan plan={plus} plus>
            {isPlus
              ? <p className="mono" style={{ color: 'var(--accent-ink)' }}>Your current plan</p>
              : <button className="btn btn-primary" onClick={upgrade} disabled={busy}>{busy ? 'Opening PayPal…' : 'Upgrade with PayPal (Sandbox)'}</button>}
          </Plan>
        </div>
      )}

      {history.length > 0 && (
        <>
          <div className="sec-head"><h2>Payment history</h2></div>
          <ul className="orders">
            {history.map((o) => (
              <li key={o.id || o.paypal_order_id}>
                <span>Subwise Plus <small className="mono">{day(o.captured_at || o.created_at)}</small></span>
                <span className="mono">{money(o.amount, o.currency)}</span>
                <small className="mono">{o.status}</small>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}