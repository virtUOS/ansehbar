// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { syncWaitDone } from "../admin";
import { ApiError, api } from "../api";

/** Triggers an immediate Opencast sync (read-only on the Opencast side).
 *  Disabled from the click until the heartbeat's `requested` flag has been
 *  seen and cleared again (or a timeout), so the user sees it is running.
 *  `requested` comes from the caller's heartbeat polling. */
export function SyncNowButton({
  requested,
  onStart,
  onDone,
  onError,
  className = "btn-secondary",
  label,
}: {
  requested: boolean;
  onStart?: () => void;
  onDone?: () => void;
  /** The request could not be started; nothing is pending any more. */
  onError?: () => void;
  className?: string;
  /** Idle label; defaults to "Sync now". */
  label?: string;
}) {
  const { t } = useTranslation();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [error, setError] = useState("");
  const seen = useRef(false);
  const waiting = startedAt !== null;

  if (waiting && requested) seen.current = true;

  useEffect(() => {
    if (startedAt === null) return;
    const check = () => {
      if (syncWaitDone({ requested, seenRequested: seen.current, elapsedMs: Date.now() - startedAt })) {
        setStartedAt(null);
        onDone?.();
      }
    };
    check();
    const id = window.setInterval(check, 1000);
    return () => window.clearInterval(id);
  }, [startedAt, requested, onDone]);

  const click = async () => {
    setError("");
    seen.current = false;
    setStartedAt(Date.now());
    onStart?.();
    try {
      await api.opencast.sync();
    } catch (e) {
      setStartedAt(null);
      onError?.();
      setError(e instanceof ApiError && e.message && !e.message.startsWith("HTTP ") ? e.message : t("Sync could not be started"));
    }
  };

  return (
    <>
      <button type="button" disabled={waiting} onClick={() => void click()} className={className}>
        {waiting ? t("Sync running…") : (label ?? t("Sync now"))}
      </button>
      {error ? (
        <span role="alert" className="text-sm font-bold">
          <span aria-hidden>⚠ </span>
          {error}
        </span>
      ) : null}
    </>
  );
}
