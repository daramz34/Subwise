import { useId } from 'react';

// Text input, or a <select> when `options` is given (strings or {value, label}).
export default function Field({ label, hint, error, options, ...rest }) {
  const id = useId();
  const errId = error ? `${id}-err` : undefined;
  const common = { id, 'aria-invalid': error ? true : undefined, 'aria-describedby': errId, ...rest };
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {options ? (
        <select {...common}>
          {options.map((o) => {
            const v = typeof o === 'string' ? o : o.value;
            const l = typeof o === 'string' ? o : o.label;
            return <option key={v} value={v}>{l}</option>;
          })}
        </select>
      ) : <input {...common} />}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span id={errId} className="err">{error}</span>}
    </div>
  );
}