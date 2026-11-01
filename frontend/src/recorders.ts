// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers for recorder lists (merge, sort, time formatting). */
import type { MonitorHealth, Recorder } from "./api";

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
  const merged = next.map((r) => {
    const old = byId.get(r.id);
    return old && same(old, r) ? old : r;
  });
  const unchanged = merged.length === prev.length && merged.every((r, i) => r === prev[i]);
  return unchanged ? prev : merged;
}

/** How a recorder is presented. "live-unknown": the last definite state was
 *  live (live_since survives an "unknown" check), so the player stays on. */
export type Presentation = "live" | "live-unknown" | "unknown" | "offline" | "inactive";

export function presentation(r: Recorder): Presentation {
  if (!r.active) return "inactive";
  if (r.status.state === "live") return "live";
  if (r.status.state === "unknown") return r.status.live_since ? "live-unknown" : "unknown";
  return "offline";
}

/** True while the player should be mounted ("live", or unknown but last seen live). */
export function keepsPlayer(r: Recorder): boolean {
  const p = presentation(r);
  return p === "live" || p === "live-unknown";
}

export function sortForOverview(list: Recorder[]): Recorder[] {
  return [...list].sort((a, b) => {
    const la = keepsPlayer(a) ? 0 : 1;
    const lb = keepsPlayer(b) ? 0 : 1;
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

/** "now" = recorders that keep their player (live, or unknown but last seen
 *  live); "all" = every recorder. The query matches room or stream name
 *  case-insensitively (for filtering only: stream names are never altered). */
export function filterOverview(list: Recorder[], mode: "now" | "all", query: string): Recorder[] {
  const q = query.trim().toLowerCase();
  return list.filter((r) => {
    if (mode === "now" && !keepsPlayer(r)) return false;
    if (!q) return true;
    return r.room_name.toLowerCase().includes(q) || r.stream_name.toLowerCase().includes(q);
  });
}

/** Recorders outside "Now", split so "unknown" is never reported as "no stream". */
export function outsideNow(list: Recorder[]): { offline: Recorder[]; unknown: Recorder[] } {
  const offline: Recorder[] = [];
  const unknown: Recorder[] = [];
  for (const r of list) {
    const p = presentation(r);
    if (p === "offline") offline.push(r);
    else if (p === "unknown") unknown.push(r);
  }
  return { offline, unknown };
}

/** Empty "Now" message: "nothing streams" only when no active recorder is unknown. */
export function emptyNowMessage(list: Recorder[]): "none-streaming" | "unclear" {
  return list.some((r) => r.active && r.status.state === "unknown") ? "unclear" : "none-streaming";
}

/** Announcement for a live<->offline change; null for first load, "unknown"
 *  or no change. */
export function stateTransition(
  prev: Recorder["status"]["state"] | undefined,
  next: Recorder["status"]["state"],
): "started" | "ended" | null {
  // Only definite states count; callers pass the last definite state.
  if (prev === undefined || prev === "unknown" || next === "unknown" || prev === next) return null;
  return next === "live" ? "started" : "ended";
}

/** The monitor counts as stale when its last check is older than three
 *  intervals (server clock), or when it never checked while active recorders
 *  exist. */
export function monitorStale(health: MonitorHealth, hasActive: boolean): boolean {
  if (!health.last_check) return hasActive;
  const age = new Date(health.now).getTime() - new Date(health.last_check).getTime();
  return age > 3 * health.interval_seconds * 1000;
}
