import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Archive, Pencil, Plus } from 'lucide-react';
import '../styles/subscriptions.css';
import { useAuth } from '../context/AuthContext';
import Modal, { ConfirmDialog } from '../components/feedback/Modal';
import SubscriptionForm from '../components/subscriptions/SubscriptionForm';
import { archiveSubscription, listCategories, listSubscriptions, setStatus } from '../services/subscriptions';
import { cadence, money, shortDate } from '../utils/format';

const PAGE = 20;
const SORTS = {
  renewal: { label: 'Next renewal', sort: 'next_renewal_date', order: 'asc' },
  name: { label: 'Name', sort: 'name', order: 'asc' },
  price: { label: 'Highest price', sort: 'amount', order: 'desc' },
  added: { label: 'Recently added', sort: 'created_at', order: 'desc' },
};
const STATUSES = [['active', 'Active'], ['trial', 'Free trial'], ['paused', 'Paused'], ['cancelled', 'Cancelled']];

export default function Subscriptions() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get('q') || '');
  const [dq, setDq] = useState(params.get('q') || '');
  const [status, setStatusFilter] = useState('');
  const [category, setCategory] = useState('');
  const [sortKey, setSortKey] = useState('renewal');
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [tick, setTick] = useState(0);
  const [data, setData] = useState(null);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editor, setEditor] = useState(null); // null | 'new' | subscription
  const [toArchive, setToArchive] = useState(null);
  const [working, setWorking] = useState(false);

    useEffect(() => {
    listCategories()
      .then((c) => setCategories(Array.isArray(c) ? c : (c && c.items) || []))
      .catch(() => {});
  }, []);
  useEffect(() => { const t = setTimeout(() => { setDq(q.trim()); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);

  useEffect(() => {
    let live = true;
    setLoading(true); setError('');
    const s = SORTS[sortKey];
    listSubscriptions({ q: dq, status, category_id: category, include_archived: archived, sort: s.sort, order: s.order, page, page_size: PAGE })
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setError(e.message); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [dq, status, category, sortKey, archived, page, tick]);

  const reload = () => setTick((t) => t + 1);
  const on = (fn) => (e) => { fn(e.target.value); setPage(1); };
  const items = data ? data.items : [];
  const filtered = !!(dq || status || category);
  const last = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;

  async function changeStatus(s, next) {
    setNotice('');
    try { await setStatus(s.id, next); } catch (e) { setNotice(e.message); }
    reload();
  }

  async function confirmArchive() {
    setWorking(true);
    try { await archiveSubscription(toArchive.id); setToArchive(null); reload(); }
    catch (e) { setNotice(e.message); setToArchive(null); }
    finally { setWorking(false); }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Subscriptions</h1>
          <p className="page-sub">{data ? `${data.total} ${data.total === 1 ? 'subscription' : 'subscriptions'}${filtered ? ' match' : ''}.` : 'Every recurring payment, in one ledger.'}</p>
        </div>
        <button className="btn btn-primary" onClick={() => setEditor('new')}><Plus size={18} aria-hidden="true" /> Add subscription</button>
      </div>

      <div className="toolbar">
        <input type="search" aria-label="Search subscriptions" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Filter by status" value={status} onChange={on(setStatusFilter)}>
          <option value="">All statuses</option>
          {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Filter by category" value={category} onChange={on(setCategory)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select aria-label="Sort by" value={sortKey} onChange={on(setSortKey)}>
          {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>Sort: {v.label}</option>)}
        </select>
        <label className="check">
          <input type="checkbox" checked={archived} onChange={(e) => { setArchived(e.target.checked); setPage(1); }} /> Show archived
        </label>
      </div>

      {notice && <div className="alert" role="alert">{notice}</div>}
      {error && <div className="alert" role="alert">{error} <button className="btn" onClick={reload}>Try again</button></div>}

      {loading && !data && <p className="page-sub">Loading your subscriptions…</p>}

      {data && items.length === 0 && !error && (
        <div className="empty">
          {filtered || archived ? (
            <><h2>Nothing matches these filters.</h2><p className="page-sub">Clear the search or filters to see everything.</p></>
          ) : (
            <>
              <h2>No subscriptions yet.</h2>
              <p className="page-sub">Add your first one by hand, or import a bank statement or receipt and review what we find.</p>
              <div className="actions">
                <button className="btn btn-primary" onClick={() => setEditor('new')}>Add subscription</button>
                <Link className="btn" to="/import">Import instead</Link>
              </div>
            </>
          )}
        </div>
      )}

      {items.length > 0 && (
        <ul className="ledger" aria-busy={loading}>
          <li className="ledger-head" aria-hidden="true"><span>Name</span><span>Cost</span><span>Next renewal</span><span>Status</span><span /></li>
          {items.map((s) => {
            const gone = !!s.archived_at;
            return (
              <li key={s.id} className={`sub-row${gone ? ' is-archived' : ''}`}>
                <div className="sub-main">
                  <strong>{s.name}</strong>
                  <span className="sub-meta">{(s.category && s.category.name) || s.merchant || 'No category'}{s.is_shared ? `, your share ${Number(s.my_share_percent)}%` : ''}</span>
                </div>
                <div className="sub-amount mono">{money(s.amount, s.currency)}<span>{cadence(s.billing_interval, s.interval_count)}</span></div>
                <div className="sub-date mono"><span>Renews</span>{shortDate(s.next_renewal_date)}</div>
                <div className="sub-status">
                  {gone ? <span className="pill">Archived</span> : (
                    <select className={`pill pill-${s.status}`} aria-label={`Status of ${s.name}`} value={s.status} onChange={(e) => changeStatus(s, e.target.value)}>
                      {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  )}
                </div>
                <div className="sub-actions">
                  {!gone && (
                    <>
                      <button className="icon-btn" aria-label={`Edit ${s.name}`} onClick={() => setEditor(s)}><Pencil size={18} /></button>
                      <button className="icon-btn" aria-label={`Archive ${s.name}`} onClick={() => setToArchive(s)}><Archive size={18} /></button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {data && data.total > PAGE && (
        <div className="pager">
          <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="mono">Page {page} of {last}</span>
          <button className="btn" disabled={page >= last} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}

      {editor && (
        <Modal title={editor === 'new' ? 'Add subscription' : `Edit ${editor.name}`} onClose={() => setEditor(null)}>
          <SubscriptionForm
            initial={editor === 'new' ? null : editor}
            categories={categories}
            defaultCurrency={user.default_currency}
            onClose={() => setEditor(null)}
            onSaved={() => { setEditor(null); reload(); }}
          />
        </Modal>
      )}

      {toArchive && (
        <ConfirmDialog
          title={`Archive ${toArchive.name}?`}
          text="It leaves your totals and renewals. Its price history stays, but an archived subscription can't be edited."
          confirmLabel="Archive"
          danger busy={working}
          onConfirm={confirmArchive}
          onCancel={() => setToArchive(null)}
        />
      )}
    </>
  );
}
