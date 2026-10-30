// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers for recorder lists (merge, sort, time formatting). */
import type { Recorder } from "./api";

function same(a: Recorder, b: Recorder): boolean {
  return (
    a.id === b.id &&
    a.room_name === b.room_name &&
    a.stream_name === b.stream_name &&
    a.active === b.active &&
    a.needs_review === b.needs_review &&
    a.playback_url === b.playback_url &&
    a.status.state === b.status.state &&
    a.status.live_since === b.status.live_since &&
    a.status.checked_at === b.status.checked_at
  );
}

/** Returns the old object for every unchanged entry (stable identity). */
export function mergeRecorders(prev: Recorder[], next: Recorder[]): Recorder[] {
  const byId = new Map(prev.map((r) => [r.id, r]));
  return next.map((r) => {
    const old = byId.get(r.id);
    return old && same(old, r) ? old : r;
  });
}

export function sortForOverview(list: Recorder[]): Recorder[] {
  return [...list].sort((a, b) => {
    const la = a.status.state === "live" ? 0 : 1;
    const lb = b.status.state === "live" ? 0 : 1;
    if (la !== lb) return la - lb;
    return a.room_name.localeCompare(b.room_name, "de", { numeric: true });
  });
}

export function formatClock(iso: string, locale: string): string {
  return new Date(iso).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

export function formatDuration(fromIso: string, now: Date): string {
  const total = Math.max(0, Math.floor((now.getTime() - new Date(fromIso).getTime()) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
