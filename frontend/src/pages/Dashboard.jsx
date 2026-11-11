import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import '../styles/dashboard.css';
import { useAuth } from '../context/AuthContext';
import { getOverview, getPriceChanges } from '../services/analytics';
import { money, shortDate } from '../utils/format';

const when = (d) => (d === 0 ? 'Today' : d === 1 ? 'Tomorrow' : `In ${d} days`);
const pct = (n) => `${Number(n) > 0 ? '+' : ''}${Number(n).toFixed(1)}%`;

export default function Dashboard() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState(null);
  const [changes, setChanges] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    Promise.allSettled([getOverview(days), getPriceChanges()]).then(([o, p]) => {
      if (!live) return;
      if (o.status === 'fulfilled') { setOverview(o.value); setError(''); }
      else setError(o.reason.message);
      setChanges(p.status === 'fulfilled' && Array.isArray(p.value) ? p.value : []);
    });
    return () => { live = false; };
  }, [days]);

  const h = new Date().getHours();
  const part = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const first = (user?.full_name || '').split(' ')[0];

  const totals = (overview && (overview.totals || overview.totals_by_currency)) || [];
  const upcoming = (overview && overview.upcoming_renewals) || [];
  const count = overview ? (overview.subscription_count ?? overview.active_count ?? totals.length) : 0;

  const byCur = {};
  ((overview && overview.by_category) || []).forEach((c) => {
    (byCur[c.currency] = byCur[c.currency] || []).push({
      name: c.category || c.category_name || 'Uncategorised',
      monthly: Number(c.monthly),
    });
  });
  const curs = Object.keys(byCur);

  return (
    <>
      <h1 className="page-title" style={{ fontSize: 'var(--step-4)', marginBottom: 32 }}>{part}, {first}.</h1>

      {error && <div className="alert" role="alert">{error}</div>}
      {!overview && !error && <p className="page-sub">Reading your numbers…</p>}

      {overview && count === 0 && (
        <div className="empty">
          <h2>Nothing to total yet.</h2>
          <p className="page-sub">Add a subscription and your monthly and yearly spend will show up here.</p>
          <div className="actions">
            <Link className="btn btn-primary" to="/subscriptions">Add a subscription</Link>
            <Link className="btn" to="/import">Import instead</Link>
          </div>
        </div>
      )}

      {overview && count > 0 && (
        <>
          <section className="spend" aria-label="Recurring spend">
            <p className="eyebrow">Recurring spend, per month</p>
            <div className="spend-row">
              {totals.map((t) => (
                <div key={t.currency}>
                  <span className="spend-num">{money(t.monthly, t.currency)}</span>
                  <span className="spend-sub mono">
                    {money(t.yearly, t.currency)} a year
                    {t.count != null ? `, ${t.count} ${t.count === 1 ? 'subscription' : 'subscriptions'}` : ''}
                  </span>
                </div>
              ))}
            </div>
            {totals.length > 1 && <p className="note">Each currency is shown on its own. Nothing is converted or added together.</p>}
          </section>

          <div className="dash-grid">
            <section>
              <div className="sec-head">
                <h2>Coming up</h2>
                <select aria-label="Renewal window" value={days} onChange={(e) => setDays(Number(e.target.value))}>
                  <option value={30}>Next 30 days</option>
                  <option value={60}>Next 60 days</option>
                  <option value={90}>Next 90 days</option>
                </select>
              </div>
              {upcoming.length === 0 ? (
                <p className="dash-empty">Nothing renews in the next {days} days.</p>
              ) : (
                <ol className="timeline">
                  {upcoming.map((r) => (
                    <li key={`${r.subscription_id}-${r.renewal_date}`} className={r.days_until <= 3 ? 'tl-soon' : ''}>
                      <span className="tl-when mono">{when(r.days_until)}</span>
                      <span className="tl-name">{r.name}<small className="mono">{shortDate(r.renewal_date)}</small></span>
                      <span className="mono">{money(r.amount, r.currency)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section>
              <div className="sec-head"><h2>Where it goes</h2></div>
              {curs.length === 0 ? (
                <p className="dash-empty">Give your subscriptions categories to see this.</p>
              ) : curs.map((cur) => {
                const rows = byCur[cur].sort((a, b) => b.monthly - a.monthly);
                const max = Math.max(...rows.map((r) => r.monthly)) || 1;
                return (
                  <div key={cur}>
                    {curs.length > 1 && <p className="eyebrow bar-cur">{cur}</p>}
                    <ul className="bars">
                      {rows.map((r) => (
                        <li key={r.name}>
                          <div className="bar-top"><span>{r.name}</span><span className="mono">{money(r.monthly, cur)}</span></div>
                          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.monthly / max) * 100}%` }} /></div>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </section>
          </div>
        </>
      )}

      {changes.length > 0 && (
        <section>
          <div className="sec-head"><h2>Price changes</h2></div>
          <ul className="changes">
            {changes.map((c) => {
              const impact = Number(c.yearly_impact);
              return (
                <li key={`${c.subscription_id}-${c.effective_date}`}>
                  <span>{c.name} <small className="mono">from {shortDate(c.effective_date)}</small></span>
                  <span className={`mono ${impact > 0 ? 'up' : 'down'}`}>{pct(c.change_percent)}</span>
                  <small className="mono">{money(c.old_amount, c.currency)} to {money(c.new_amount, c.currency)}</small>
                  <small className="mono">{impact > 0 ? 'adds' : 'saves'} {money(Math.abs(impact), c.currency)} a year</small>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {overview && (
        <div className="nudge">
          <p>Ask questions about your own saved subscriptions.</p>
          <Link className="btn" to="/intelligence">Ask the AI analyst</Link>
        </div>
      )}
    </>
  );
}