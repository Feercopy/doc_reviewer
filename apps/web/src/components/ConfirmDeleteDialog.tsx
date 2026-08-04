"use client";

import { useEffect } from "react";

type ConfirmDeleteDialogProps = {
  busy?: boolean;
  message: string;
  onCancel: () => void;
  onDelete: () => void;
};

export function ConfirmDeleteDialog({ busy = false, message, onCancel, onDelete }: ConfirmDeleteDialogProps) {
  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel]);

  return (
    <div
      className="confirm-delete-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busy) {
          onCancel();
        }
      }}
    >
      <section
        aria-labelledby="confirm-delete-title"
        aria-modal="true"
        className="confirm-delete-dialog"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-delete-title">{message}</h2>
        <div className="confirm-delete-actions">
          <button className="danger" disabled={busy} type="button" onClick={onDelete}>
            {busy ? "Deleting" : "Delete"}
          </button>
          <button className="secondary" disabled={busy} type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </section>
    </div>
  );
}
