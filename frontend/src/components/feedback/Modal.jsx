import { useEffect, useRef } from 'react';

// Native <dialog>: focus trap and Escape handling come from the browser.
export default function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => { if (d && d.open) d.close(); };
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby="modal-title"
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
    >
      <div className="modal-body">
        <h2 id="modal-title">{title}</h2>
        {children}
      </div>
    </dialog>
  );
}

export function ConfirmDialog({ title, text, confirmLabel, busy, danger, onConfirm, onCancel }) {
  return (
    <Modal title={title} onClose={onCancel}>
      <p className="page-sub" style={{ marginBottom: 24 }}>{text}</p>
      <div className="form-actions">
        <button className="btn" onClick={onCancel} disabled={busy}>Keep it</button>
        <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
