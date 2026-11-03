// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Polls the recorder list and the monitor heartbeat; pauses while the tab is
 *  hidden. A 403 means the access gate changed, so `onForbidden` lets the App
 *  re-check whoami. */
import { useEffect, useRef, useState } from "react";
import { useAppContext } from "./appContext";
import { ApiError, api, type Recorder } from "./api";
import { DEFAULT_SLOTS, mergeRecorders, monitorStale, opencastNotice, opencastStale } from "./recorders";

export function useRecorders(intervalMs = 8000, onForbidden?: () => void) {
  const [recorders, setRecorders] = useState<Recorder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  // Primitives, so an unchanged heartbeat does not re-render the page.
  const [stale, setStale] = useState(false);
  const [lastCheck, setLastCheck] = useState<string | null>(null);
  const [ocEnabled, setOcEnabled] = useState(false);
  const [ocStale, setOcStale] = useState(false);
  const [ocLastSuccess, setOcLastSuccess] = useState<string | null>(null);
  const [ocErrorKind, setOcErrorKind] = useState("");
  const [ocNotice, setOcNotice] = useState<{ level: "error" | "hint" | null; key: string | null }>({ level: null, key: null });
  const [ocRequested, setOcRequested] = useState(false);
  const [slotMinutes, setSlotMinutes] = useState(DEFAULT_SLOTS.minutes);
  const [slotOffset, setSlotOffset] = useState(DEFAULT_SLOTS.offset_minutes);
  // Outside the app shell the context is undefined: fall back to a no-op.
  const ctx = useAppContext();
  const forbidden = useRef<(() => void) | undefined>();
  forbidden.current = onForbidden ?? ctx?.refreshWhoami;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let seq = 0; // request counter: only the newest response is applied

    const tick = async () => {
      if (document.hidden) return;
      const mine = ++seq;
      try {
        const next = await api.recorders.list();
        if (cancelled || mine !== seq) return;
        setRecorders((prev) => mergeRecorders(prev, next));
        setError(null);
        setLastUpdated(new Date());
        try {
          const health = await api.monitor.health();
          if (cancelled || mine !== seq) return;
          setStale(monitorStale(health, next.some((r) => r.active)));
          setLastCheck(health.last_check);
          setOcEnabled(health.opencast.enabled);
          setOcStale(opencastStale(health));
          setOcLastSuccess(health.opencast.last_success);
          const notice = opencastNotice(health);
          setOcNotice((prev) => (prev.level === notice.level && prev.key === notice.key ? prev : notice));
          setOcRequested(health.opencast.requested);
          setOcErrorKind(health.opencast.error_kind);
          setSlotMinutes(health.slots.minutes);
          setSlotOffset(health.slots.offset_minutes);
        } catch {
          /* heartbeat unavailable: keep the last known verdict */
        }
      } catch (e) {
        if (cancelled || mine !== seq) return;
        if (e instanceof ApiError && e.status === 403) forbidden.current?.();
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled && mine === seq) setLoading(false);
      }
    };
    // Exactly one pending timer: every (re)start clears the previous one.
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        await tick();
        if (!cancelled) schedule();
      }, intervalMs);
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
  }, [intervalMs]);

  /** monitorStale: the monitor has not checked for > 3 intervals (server clock). */
  return {
    recorders,
    error,
    loading,
    lastUpdated,
    monitorStale: stale,
    monitorLastCheck: lastCheck,
    opencastEnabled: ocEnabled,
    opencastStale: ocStale,
    opencastLastSuccess: ocLastSuccess,
    opencastErrorKind: ocErrorKind,
    opencastNotice: ocNotice,
    opencastRequested: ocRequested,
    slotMinutes,
    slotOffset,
  };
}
