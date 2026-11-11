import { useState } from 'react';
import { Link } from 'react-router-dom';
import '../styles/import.css';
import { ConfirmDialog } from '../components/feedback/Modal';
import Field from '../components/forms/Field';
import { confirmImport, createEmailImport, createFileImport, getImport, getItems, undoImport } from '../services/imports';

const MAX = 5 * 1024 * 1024;
const INTERVALS = [
  { value: 'month', label: 'Monthly' }, { value: 'year', label: 'Yearly' },
  { value: 'week', label: 'Weekly' }, { value: 'day', label: 'Daily' },
];
const METHODS = { ai: 'Read by AI', pattern: 'Pattern match', both: 'AI and pattern' };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function kindOf(file) {
  const e = (file.name.split('.').pop() || '').toLowerCase();
  if (e === 'csv') return 'csv';
  if (e === 'pdf') return 'pdf';
  return ['png', 'jpg', 'jpeg'].includes(e) ? 'image' : null;
}

const NOTICES = {
  csv: ['CSV: no AI involved', "Subwise reads this file with its own fixed pattern rules. It is not sent to any AI service. The file is kept on the Subwise server while you review it."],
  pdf: ['PDF: sent to a third-party AI service', 'This file goes as it is to Google Gemini so it can be read. It is NOT redacted, so anything visible in it, such as names, addresses or card digits, goes with it. Only upload files you are comfortable sharing.'],
  image: ['Image: sent to a third-party AI service', 'This image goes as it is to Google Gemini so it can be read. It is NOT redacted, so anything visible in it goes with it. Only upload images you are comfortable sharing.'],
  email: ['Pasted email: redacted, then sent to a third-party AI service', 'Subwise automatically redacts personal details from the text before sending it to Google Gemini. Redaction is automatic and not perfect, so remove anything sensitive yourself first.'],
  none: ['Before you import', 'CSV files are read by Subwise itself, with no AI. PDFs and images are sent to a third-party AI service exactly as they are. Pasted emails are redacted first, then sent to that AI service.'],
};

function lowConf(src, key) {
  const fc = src.field_confidence || {};
  const names = { name: ['name', 'extracted_name'], amount: ['amount', 'extracted_amount'], currency: ['currency', 'extracted_currency'], interval: ['interval', 'extracted_interval'], date: ['date', 'charge_date', 'extracted_date'] }[key];
  return names.some((k) => fc[k] != null && Number(fc[k]) < 0.7);
}

function problem(d) {
  if (!d.name.trim()) return 'Add a name.';
  if (!/^\d+(\.\d{1,2})?$/.test(d.amount.trim())) return 'Add an amount with up to 2 decimals.';
  if (!/^[A-Za-z]{3}$/.test(d.currency.trim())) return 'Add a 3-letter currency, like USD.';
  return '';
}

function edits(d) {
  const s = d.src;
  const e = {};
  if (d.name.trim() !== (s.extracted_name || '')) e.extracted_name = d.name.trim();
  if (d.amount.trim() && (s.extracted_amount == null || Number(d.amount) !== Number(s.extracted_amount))) e.extracted_amount = d.amount.trim();
  const cur = d.currency.trim().toUpperCase();
  if (cur && cur !== s.extracted_currency) e.extracted_currency = cur;
  if (d.interval !== s.extracted_interval) e.extracted_interval = d.interval;
  if (d.date && d.date !== s.extracted_date) e.extracted_date = d.date;
  return e;
}

export default function ImportCentre() {
  const [mode, setMode] = useState('file');
  const [file, setFile] = useState(null);
  const [text, setText] = useState('');
  const [ack, setAck] = useState(false);
  const [step, setStep] = useState('source'); // source | working | review | empty | done
  const [error, setError] = useState('');
  const [needsPlus, setNeedsPlus] = useState(false);
  const [job, setJob] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [undone, setUndone] = useState(false);
  const [askUndo, setAskUndo] = useState(false);

  const kind = mode === 'email' ? 'email' : file ? kindOf(file) : null;
  const needsAck = kind === 'pdf' || kind === 'image';
  const ready = mode === 'email' ? text.trim().length >= 20 : !!file && (!needsAck || ack);
  const patch = (id, p) => setDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, ...p } : d)));

  function pick(e) {
    const f = e.target.files && e.target.files[0];
    setError(''); setAck(false); setFile(null);
    if (!f) return;
    if (!kindOf(f)) return setError('Use a CSV, PDF, PNG or JPG file.');
    if (f.size > MAX) return setError('That file is over 5 MB.');
    setFile(f);
  }

  function fail(e) { setNeedsPlus(e.status === 403); setError(e.message); setStep('source'); }

  async function start(ev) {
    ev.preventDefault();
    setError(''); setNeedsPlus(false); setStep('working');
    try {
      let j = mode === 'email' ? await createEmailImport(text.trim()) : await createFileImport(file);
      for (let i = 0; i < 30 && (j.status === 'processing' || j.status === 'uploaded'); i++) {
        await wait(2000);
        j = await getImport(j.id);
      }
      if (j.status === 'failed') throw new Error(j.error_message || 'We could not read that source.');
      if (j.status !== 'review') return setStep('empty');
      const items = await getItems(j.id);
      const list = (Array.isArray(items) ? items : []).filter((i) => i.status === 'pending');
      if (list.length === 0) return setStep('empty');
      setJob(j);
      setDrafts(list.map((i) => ({
        id: i.id, src: i,
        keep: !i.duplicate_of_id && i.extracted_amount != null && !!i.extracted_name,
        name: i.extracted_name || '',
        amount: i.extracted_amount == null ? '' : String(i.extracted_amount),
        currency: i.extracted_currency || '',
        interval: i.extracted_interval || 'month',
        date: i.extracted_date || '',
      })));
      setShowErrors(false);
      setStep('review');
    } catch (e) { fail(e); }
  }

  async function save() {
    setError('');
    if (drafts.some((d) => d.keep && problem(d))) return setShowErrors(true);
    const decisions = drafts.map((d) => {
      if (!d.keep) return { item_id: d.id, action: 'reject' };
      const e = edits(d);
      return Object.keys(e).length ? { item_id: d.id, action: 'confirm', edits: e } : { item_id: d.id, action: 'confirm' };
    });
    setBusy(true);
    try {
      setResult(await confirmImport(job.id, decisions));
      setUndone(false); setStep('done');
    } catch (e) { setNeedsPlus(e.status === 403); setError(e.message); }
    finally { setBusy(false); }
  }

  async function undo() {
    setBusy(true);
    try { await undoImport(job.id); setUndone(true); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); setAskUndo(false); }
  }

  function reset() {
    setStep('source'); setFile(null); setText(''); setAck(false); setError(''); setNeedsPlus(false);
    setJob(null); setDrafts([]); setResult(null); setUndone(false);
  }

  const alert = error && (
    <div className="alert" role="alert">
      {error} {needsPlus && <Link to="/upgrade">See the Plus plan</Link>}
    </div>
  );
  const [nTitle, nText] = NOTICES[kind || 'none'];
  const kept = drafts.filter((d) => d.keep).length;

  return (
    <>
      <h1 className="page-title">Import</h1>
      <p className="page-sub">Bring subscriptions in from a bank statement, a receipt or a pasted email. You review everything before anything is saved.</p>

      {step === 'source' && (
        <form onSubmit={start}>
          {alert}
          <div className="modes" role="group" aria-label="Source">
            <button type="button" className="mode" aria-pressed={mode === 'file'} onClick={() => { setMode('file'); setError(''); }}>Upload a file</button>
            <button type="button" className="mode" aria-pressed={mode === 'email'} onClick={() => { setMode('email'); setError(''); }}>Paste an email</button>
          </div>
          {mode === 'file' ? (
            <div className="drop">
              <label htmlFor="imp-file">CSV, PDF, PNG or JPG, up to 5 MB</label>
              <input id="imp-file" type="file" accept=".csv,.pdf,.png,.jpg,.jpeg" onChange={pick} />
              {file && <span className="mono">{file.name}</span>}
            </div>
          ) : (
            <>
              <textarea className="paste" aria-label="Pasted email text" maxLength={20000} placeholder="Paste a receipt or renewal email here" value={text} onChange={(e) => setText(e.target.value)} />
              <p className="count mono">{text.length} / 20000 (at least 20)</p>
            </>
          )}
          <div className="disclose"><strong>{nTitle}</strong>{nText}</div>
          <div className="src-actions">
            {needsAck ? (
              <label className="check">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                I understand this {kind === 'pdf' ? 'PDF' : 'image'} is sent to a third-party AI service unredacted.
              </label>
            ) : <span />}
            <button className="btn btn-primary" disabled={!ready}>Read it</button>
          </div>
        </form>
      )}

      {step === 'working' && <p className="page-sub" role="status">Reading your {mode === 'email' ? 'email' : 'file'}. This can take up to a minute.</p>}

      {step === 'empty' && (
        <div className="empty">
          <h2>We did not find any subscriptions.</h2>
          <p className="page-sub">In a CSV, a subscription shows up when the same merchant charges a similar amount at regular intervals. For a receipt, make sure the name and amount are readable.</p>
          <div className="actions"><button className="btn btn-primary" onClick={reset}>Try another</button></div>
        </div>
      )}

      {step === 'review' && (
        <>
          {alert}
          <p className="legend">Check what was found. Fields outlined in lime were read with low confidence. Change anything that is wrong, or skip what you do not want.</p>
          <ul className="review">
            {drafts.map((d) => {
              const s = d.src;
              const msg = showErrors && d.keep ? problem(d) : '';
              return (
                <li key={d.id} className={`ritem${d.keep ? '' : ' skipped'}`}>
                  <div className="rhead">
                    <div className="badges">
                      {s.confidence != null && <span className="badge mono">{Math.round(Number(s.confidence) * 100)}% sure</span>}
                      <span className="badge">{METHODS[s.detection_method] || s.detection_method}</span>
                      {s.occurrences_count > 1 && <span className="badge mono">Seen {s.occurrences_count} times</span>}
                      {s.duplicate_of_id && <span className="badge warn">Looks like one you already track</span>}
                    </div>
                    <div className="seg" role="group" aria-label={`Decision for ${d.name || 'item'}`}>
                      <button type="button" aria-pressed={d.keep} onClick={() => patch(d.id, { keep: true })}>Keep</button>
                      <button type="button" aria-pressed={!d.keep} onClick={() => patch(d.id, { keep: false })}>Skip</button>
                    </div>
                  </div>
                  <div className="rgrid">
                    <Field label="Name" value={d.name} onChange={(e) => patch(d.id, { name: e.target.value })} className={lowConf(s, 'name') ? 'low' : undefined} />
                    <Field label="Amount" inputMode="decimal" value={d.amount} onChange={(e) => patch(d.id, { amount: e.target.value })} className={lowConf(s, 'amount') ? 'low' : undefined} />
                    <Field label="Currency" maxLength={3} value={d.currency} onChange={(e) => patch(d.id, { currency: e.target.value })} className={lowConf(s, 'currency') ? 'low' : undefined} />
                    <Field label="Billed" options={INTERVALS} value={d.interval} onChange={(e) => patch(d.id, { interval: e.target.value })} className={lowConf(s, 'interval') ? 'low' : undefined} />
                    <Field label="Last charge" type="date" value={d.date} onChange={(e) => patch(d.id, { date: e.target.value })} className={lowConf(s, 'date') ? 'low' : undefined} />
                  </div>
                  {msg && <p className="rerr" role="alert">{msg}</p>}
                </li>
              );
            })}
          </ul>
          <div className="rfoot">
            <p>{kept} of {drafts.length} will be saved. Nothing is saved until you confirm.</p>
            <div className="form-actions">
              <button className="btn" onClick={reset} disabled={busy}>Cancel</button>
              <button className="btn btn-primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : `Save ${kept} ${kept === 1 ? 'subscription' : 'subscriptions'}`}</button>
            </div>
          </div>
        </>
      )}

      {step === 'done' && result && (
        <div className="empty">
          {alert}
          <h2>{undone ? 'Import undone.' : `${result.created_subscription_ids.length} ${result.created_subscription_ids.length === 1 ? 'subscription' : 'subscriptions'} added.`}</h2>
          <p className="page-sub">
            {undone
              ? 'The subscriptions this import created were archived.'
              : `${result.rejected_count} skipped by you${result.skipped_count ? `, ${result.skipped_count} left untouched` : ''}.`}
          </p>
          <div className="done-row">
            <Link className="btn btn-primary" to="/subscriptions">View subscriptions</Link>
            {!undone && <button className="btn" onClick={() => setAskUndo(true)}>Undo this import</button>}
            <button className="btn" onClick={reset}>Import another</button>
          </div>
        </div>
      )}

      {askUndo && (
        <ConfirmDialog
          title="Undo this import?"
          text="The subscriptions it created will be archived. You can still see them under Show archived."
          confirmLabel="Undo import"
          danger busy={busy}
          onConfirm={undo}
          onCancel={() => setAskUndo(false)}
        />
      )}
    </>
  );
}