import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import '../styles/ai.css';
import { askAI } from '../services/ai';
import { getEntitlement } from '../services/payments';

const IDEAS = [
  'What is my total yearly spend?',
  'Which subscription renews next?',
  'Which subscriptions cost the most each month?',
  'Have any of my prices gone up?',
];

function Answer({ text, citations }) {
  return text.split('\n').filter((l) => l.trim()).map((line, i) => (
    <p key={i} className={line.trim().startsWith('Verify this') ? 'verify' : ''}>
      {line.split(/(\[S\d+\])/).map((part, j) => {
        const m = part.match(/^\[(S\d+)\]$/);
        return m ? <sup key={j} className="ref mono">{m[1]}</sup> : part;
      })}
    </p>
  ));
}

export default function Intelligence() {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [locked, setLocked] = useState(false);

  useEffect(() => {
    getEntitlement()
      .then((e) => {
        const code = (e && (e.plan_code || (e.plan && e.plan.code))) || 'free';
        if (code !== 'plus' || (e.status && e.status !== 'active')) setLocked(true);
      })
      .catch(() => {});
  }, []);

  async function submit(e) {
    e.preventDefault();
    const question = q.trim();
    if (question.length < 3) return setError('Ask a question of at least 3 characters.');
    setError(''); setBusy(true);
    try {
      const r = await askAI(question);
      setResult({ question, answer: r.answer || '', citations: r.citations || [], note: r.note || '' });
    } catch (err) {
      if (err.status === 403) setLocked(true);
      else setError(err.message);
    } finally { setBusy(false); }
  }

  return (
    <>
      <h1 className="page-title">AI Intelligence</h1>
      <p className="page-sub">Ask a question and get an answer built from your own saved subscriptions. The analyst reads your records and never changes them.</p>

      {locked ? (
        <div className="nudge">
          <p>The AI analyst is part of the Plus plan.</p>
          <Link className="btn btn-primary" to="/upgrade">See Plus</Link>
        </div>
      ) : (
        <>
          <form className="ask" onSubmit={submit}>
            <textarea
              aria-label="Your question"
              placeholder="What would you like to know?"
              maxLength={500}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <div className="ask-bar">
              <span className="count mono">{q.length} / 500</span>
              <button className="btn btn-primary" disabled={busy || q.trim().length < 3}>{busy ? 'Reading your subscriptions…' : 'Ask'}</button>
            </div>
          </form>
          <p className="privacy">
            Your subscription names, amounts, dates and categories are sent to a third-party AI service (Google Gemini) to answer. Your notes are never sent.
          </p>
          <div className="ideas">
            {IDEAS.map((i) => <button key={i} type="button" className="idea" onClick={() => setQ(i)}>{i}</button>)}
          </div>
        </>
      )}

      {error && <div className="alert" role="alert">{error}</div>}
      {busy && <p className="page-sub" role="status">Reading your subscriptions…</p>}

      {result && !busy && (
        <section className="result" aria-live="polite">
          <p className="eyebrow">You asked</p>
          <p className="asked">{result.question}</p>
          <div className="answer"><Answer text={result.answer} citations={result.citations} /></div>
          {result.citations.length > 0 && (
            <div className="sources">
              {result.citations.map((c) => (
                <Link key={c.ref} className="chip" to={`/subscriptions?q=${encodeURIComponent(c.name)}`}>
                  <b className="mono">{c.ref}</b>{c.name}
                </Link>
              ))}
            </div>
          )}
          <p className="ai-note">{result.note || 'AI can make mistakes. Check important details against your records.'}</p>
        </section>
      )}
    </>
  );
}