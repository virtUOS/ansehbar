// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Loads one event's detail (incidents, level samples) and reloads it every
 *  `refreshMs` (`null`: load once, no reload); pauses while the tab is hidden. `id = null` loads nothing. A
 *  new id drops the old state at once; responses for a stale id are ignored. */
import { useEffect, useState } from "react";
import { api, type EventDetail } from "./api";

export function useEventDetail(id: number | null, refreshMs: number | null = 30000) {
  // Keyed by id, so a stale detail is never returned, not even for one render.
  const [state, setState] = useState<{ id: number | null; detail: EventDetail | null; error: string | null }>({
    id,
    detail: null,
    error: null,
  });

  useEffect(() => {
    // Keep the detail when only `refreshMs` changed (same id).
    setState((prev) => (prev.id === id ? prev : { id, detail: null, error: null }));
    if (id === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let seq = 0; // request counter: only the newest response is applied

    const tick = async () => {
      if (document.hidden) return;
      const mine = ++seq;
      try {
        const detail = await api.event(id);
        if (cancelled || mine !== seq) return;
        setState({ id, detail, error: null });
      } catch (e) {
        if (cancelled || mine !== seq) return;
        // Keep the last detail; show the error alongside.
        setState((prev) => ({ ...prev, id, error: e instanceof Error ? e.message : String(e) }));
      }
    };
    // Exactly one pending timer: every (re)start clears the previous one.
    const schedule = () => {
      if (refreshMs === null) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        await tick();
        if (!cancelled) schedule();
      }, refreshMs);
    };
    const onVisible = () => {
      if (document.hidden) return;
      void tick();
      schedule();
    };

    void tick();
    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [id, refreshMs]);

  const current = state.id === id;
  return { detail: current ? state.detail : null, error: current ? state.error : null };
}
