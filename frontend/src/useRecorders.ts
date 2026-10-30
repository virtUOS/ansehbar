// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Polls the recorder list; pauses while the tab is hidden. A 403 means the
 *  access gate changed, so `onForbidden` lets the App re-check whoami. */
import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Recorder } from "./api";
import { mergeRecorders } from "./recorders";

export function useRecorders(intervalMs = 8000, onForbidden?: () => void) {
  const [recorders, setRecorders] = useState<Recorder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const forbidden = useRef(onForbidden);
  forbidden.current = onForbidden;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      if (document.hidden) return;
      try {
        const next = await api.recorders.list();
        if (cancelled) return;
        setRecorders((prev) => mergeRecorders(prev, next));
        setError(null);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) forbidden.current?.();
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    const schedule = () => {
      timer = setTimeout(async () => {
        await tick();
        if (!cancelled) schedule();
      }, intervalMs);
    };
    const onVisible = () => {
      if (!document.hidden) void tick();
    };

    void tick();
    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs]);

  return { recorders, error, loading };
}
