// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Create a GitLab ticket for a recorder (message + optional screenshot).
 *  Native <dialog> like ConfirmDialog. Render only while open. */
import { useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api, type Recorder } from "../api";
import { displayName } from "../recorders";

interface Props {
  recorder: Recorder;
  screenshot: Blob | null;
  onClose: () => void;
}

export function TicketDialog({ recorder, screenshot, onClose }: Props) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();
  const fieldId = useId();
  const errId = `${fieldId}-err`;
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<string[]>([]);
  const [webUrl, setWebUrl] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const previewUrl = useMemo(() => (screenshot ? URL.createObjectURL(screenshot) : null), [screenshot]);
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    textRef.current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      trigger?.focus?.();
    };
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!message.trim() || sending) return;
    setSending(true);
    setError("");
    setFieldErrors([]);
    try {
      const result = await api.recorders.ticket(recorder.id, message.trim(), screenshot);
      setWebUrl(result.web_url);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setFieldErrors([...(err.fieldErrors.message ?? []), ...(err.fieldErrors.screenshot ?? [])]);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setSending(false);
    }
  };

  const safeUrl = webUrl && /^https?:\/\//i.test(webUrl) ? webUrl : null;
  const room = displayName(recorder);

  return createPortal(
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className="m-auto h-fit max-h-[calc(100%-2rem)] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-xl border border-slate-300 bg-white p-5 text-slate-900 backdrop:bg-black/40 dark:backdrop:bg-black/60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
    >
      <h2 id={titleId} className="text-lg font-bold">
        {t("Create ticket for {{room}}", { room })}
      </h2>
      {done ? (
        <div className="mt-3 space-y-3 text-sm">
          <p role="status" className="font-medium">
            <span aria-hidden>✓ </span>
            {t("Ticket created.")}
          </p>
          {safeUrl ? (
            <p>
              <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="font-medium underline">
                {t("Open ticket")}
              </a>
            </p>
          ) : null}
          <div className="flex justify-end">
            <button type="button" onClick={onClose} className="btn-secondary">
              {t("Close")}
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-3 text-sm">
          {previewUrl ? (
            <img src={previewUrl} alt={t("Screenshot of the stream")} className="max-h-48 w-full rounded-lg bg-black object-contain" />
          ) : (
            <p className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800">
              {t("No screenshot available – the ticket will be sent without one.")}
            </p>
          )}
          <div>
            <label htmlFor={fieldId} className="mb-1 block font-medium">
              {t("Error description")}
            </label>
            <textarea
              id={fieldId}
              ref={textRef}
              required
              maxLength={2000}
              rows={5}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              aria-invalid={fieldErrors.length ? true : undefined}
              aria-describedby={fieldErrors.length ? errId : undefined}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm aria-[invalid=true]:border-red-700 dark:border-slate-700 dark:bg-slate-900 dark:aria-[invalid=true]:border-red-400"
            />
            {fieldErrors.length ? (
              <p id={errId} className="mt-1 font-medium text-red-800 dark:text-red-300">
                <span aria-hidden>⚠ </span>
                {fieldErrors.join(" ")}
              </p>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 font-medium text-red-900">
              <span aria-hidden>⚠ </span>
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary">
              {t("Cancel")}
            </button>
            <button type="submit" disabled={!message.trim() || sending} className="btn-primary">
              {sending ? t("Creating…") : t("Create ticket")}
            </button>
          </div>
        </form>
      )}
    </dialog>,
    document.body,
  );
}
