// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Accessible confirm dialog on the native <dialog> element: modal (focus
 *  trap, inert background), Escape cancels, initial focus on Cancel, focus
 *  returns to the trigger. Render it only while a question is pending. */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, children, confirmLabel, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const cancelBtn = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    cancelBtn.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      trigger?.focus?.();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault(); // we unmount ourselves
        onCancel();
      }}
      className="w-[calc(100%-2rem)] max-w-md rounded-xl border border-slate-300 bg-white p-5 text-slate-900 backdrop:bg-black/50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
    >
      <h2 id={titleId} className="text-lg font-bold">
        {title}
      </h2>
      {children ? <div className="mt-2 text-sm">{children}</div> : null}
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button ref={cancelBtn} type="button" onClick={onCancel} className="btn-secondary">
          {t("Cancel")}
        </button>
        <button type="button" onClick={onConfirm} className="btn-danger">
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
