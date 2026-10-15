"use client";
import { useId, useRef, useState } from "react";

/**
 * A button that asks in a dialog before it acts. The dialog's confirm button is the real submit
 * button and carries this button's `name`/`value`, so a form holding several buttons only ever
 * sends the action that was confirmed. Escape, Cancel or a click beside the dialog closes it.
 */
export function ConfirmButton({ children, title, message, confirmLabel, className, name = "action", value }: {
  children: React.ReactNode;
  /** The question, e.g. "Lock PC082?" */
  title: string;
  /** What will happen, in a sentence or two. */
  message: React.ReactNode;
  /** The confirm button's label; defaults to the button's own text. */
  confirmLabel?: string;
  className?: string;
  name?: string;
  value: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [sending, setSending] = useState(false);
  const id = useId();
  const close = () => dialog.current?.close();
  return (
    <>
      <button type="button" className={className ?? "btn btn-danger btn-small"} onClick={() => dialog.current?.showModal()}>
        {children}
      </button>
      <dialog
        ref={dialog}
        className="modal"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-text`}
        onClick={(event) => { if (event.target === event.currentTarget) close(); }}
        onClose={() => setSending(false)}
      >
        <div className="modal-body">
          <div className="modal-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
              <path d="M12 9v4M12 17h.01" />
            </svg>
          </div>
          <div className="min-w-0">
            <h2 id={`${id}-title`} className="modal-title">{title}</h2>
            <div id={`${id}-text`} className="modal-text">{message}</div>
          </div>
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={close}>Cancel</button>
          <button
            type="submit"
            name={name}
            value={value}
            className="btn btn-danger-solid"
            onClick={(event) => { if (sending) event.preventDefault(); else setSending(true); }}
          >
            {sending ? "Working…" : confirmLabel ?? children}
          </button>
        </div>
      </dialog>
    </>
  );
}
