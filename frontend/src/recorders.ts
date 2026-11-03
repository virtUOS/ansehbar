// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers for recorder lists (merge, sort, time formatting). */
import type { EventBrief, LastRecording, MonitorHealth, Recorder } from "./api";

function sameEvent(a: EventBrief | null, b: EventBrief | null): boolean {
  if (!a || !b) return a === b;
  return a.title === b.title && a.series === b.series && a.start === b.start && a.end === b.end;
}

function sameLastRecording(a: LastRecording | null, b: LastRecording | null): boolean {
  if (!a || !b) return a === b;
  return (
    a.title === b.title &&
    a.start === b.start &&
    a.end === b.end &&
    a.opencast_status === b.opencast_status &&
    JSON.stringify(a.problems) === JSON.stringify(b.problems)
  );
}

function same(a: Recorder, b: Recorder): boolean {
  return (
    a.id === b.id &&
    a.agent_id === b.agent_id &&
    a.missing_since === b.missing_since &&
    a.status.agent_state === b.status.agent_state &&
    a.status.agent_updated_at === b.status.agent_updated_at &&
    sameEvent(a.current_event, b.current_event) &&
    sameEvent(a.next_event, b.next_event) &&
    sameEvent(a.next_event_tomorrow, b.next_event_tomorrow) &&
    sameLastRecording(a.last_recording, b.last_recording) &&
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
export type Presentation = "live" | "live-unknown" | "unknown" | "offline" | "inactive" | "missing";

export function presentation(r: Recorder): Presentation {
  if (!r.active) return "inactive";
  if (r.status.state === "live") return "live";
  if (r.status.state === "unknown") return r.status.live_since ? "live-unknown" : "unknown";
  return r.missing_since ? "missing" : "offline";
}

/** True while the player should be mounted ("live", or unknown but last seen live). */
export function keepsPlayer(r: Recorder): boolean {
  const p = presentation(r);
  return p === "live" || p === "live-unknown";
}

export function displayName(r: Recorder): string {
  return r.room_name.trim() || r.agent_id || r.stream_name;
}

export function roomNameMissing(r: Recorder): boolean {
  return r.room_name.trim() === "";
}

export function sortForOverview(list: Recorder[]): Recorder[] {
  const group = (r: Recorder) => (presentation(r) === "missing" ? 0 : keepsPlayer(r) ? 1 : 2);
  return [...list].sort((a, b) => {
    const d = group(a) - group(b);
    if (d !== 0) return d;
    return displayName(a).localeCompare(displayName(b), "de", { numeric: true });
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

export type OverviewMode = "now" | "today" | "all";

/** "now" = player kept or stream missing; "today" = now or any event (current
 *  or next); "all" = every recorder. The query matches room, stream or agent
 *  case-insensitively (for filtering only: names are never altered). */
export function filterOverview(list: Recorder[], mode: OverviewMode, query: string): Recorder[] {
  const q = query.trim().toLowerCase();
  return list.filter((r) => {
    if (mode !== "all") {
      const now = keepsPlayer(r) || presentation(r) === "missing";
      if (!now && !(mode === "today" && (r.current_event || r.next_event))) return false;
    }
    if (!q) return true;
    return (
      r.room_name.toLowerCase().includes(q) ||
      r.stream_name.toLowerCase().includes(q) ||
      (r.agent_id ?? "").toLowerCase().includes(q)
    );
  });
}

/** Active recorders with a next event, soonest first. */
export function upcomingToday(list: Recorder[], _now: Date): Recorder[] {
  return list
    .filter((r) => r.active && r.next_event)
    .sort((a, b) => new Date(a.next_event!.start).getTime() - new Date(b.next_event!.start).getTime());
}

/** Active recorders with an event tomorrow, soonest first. */
export function upcomingTomorrow(list: Recorder[]): Recorder[] {
  return list
    .filter((r) => r.active && r.next_event_tomorrow)
    .sort(
      (a, b) =>
        new Date(a.next_event_tomorrow!.start).getTime() - new Date(b.next_event_tomorrow!.start).getTime(),
    );
}

/** Tomorrow's schedule is shown from 17:00 local time, or earlier when
 *  nothing is running or left today. */
export function showTomorrow(list: Recorder[], now: Date): boolean {
  if (now.getHours() >= 17) return true;
  return !list.some((r) => r.active && (r.current_event || r.next_event));
}

/** Active recorders that "today" would not show. */
export function quietToday(list: Recorder[]): Recorder[] {
  const shown = new Set(filterOverview(list, "today", "").map((r) => r.id));
  return list.filter((r) => r.active && !shown.has(r.id));
}

/** Time until `startIso`, floored to minutes, never negative. */
export function untilParts(startIso: string, now: Date): { hours: number; minutes: number } {
  const mins = Math.max(0, Math.floor((new Date(startIso).getTime() - now.getTime()) / 60000));
  return { hours: Math.floor(mins / 60), minutes: mins % 60 };
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

/** Opencast sync counts as stale without success or after > 3 sync intervals
 *  (server clock); never when Opencast is not enabled. */
export function opencastStale(health: MonitorHealth): boolean {
  const oc = health.opencast;
  if (!oc.enabled) return false;
  if (!oc.last_success) return true;
  const age = new Date(health.now).getTime() - new Date(oc.last_success).getTime();
  return age > 3 * oc.sync_seconds * 1000;
}

export type OpencastNotice = { level: "error" | "hint" | null; key: string | null };

const OPENCAST_ERRORS: Record<string, string> = {
  unreachable: "Opencast not reachable",
  auth: "Opencast rejected the login",
  forbidden: "No permission in Opencast",
  timeout: "Opencast did not answer in time",
  server: "Opencast server error",
  invalid: "Unexpected answer from Opencast",
  internal: "Internal error during the Opencast sync",
};

/** Notice key for an OPENCAST_URL refused as plain http://; no sync button. */
export const OPENCAST_INSECURE = "Opencast sync disabled – OPENCAST_URL must use https://";

/** Immediate Opencast message: an error for a failed sync or an insecure
 *  URL, a hint when the sync works but shows no scheduled recordings.
 *  Unknown kinds count as a server error; nothing when Opencast is off or the
 *  last sync was fine. */
export function opencastNotice(health: MonitorHealth): OpencastNotice {
  const { enabled, error_kind: kind, insecure_url } = health.opencast;
  if (insecure_url) return { level: "error", key: OPENCAST_INSECURE };
  if (!enabled || !kind) return { level: null, key: null };
  if (kind === "no_events")
    return { level: "hint", key: "Opencast shows no scheduled recordings – check the account's permissions" };
  return { level: "error", key: OPENCAST_ERRORS[kind] ?? OPENCAST_ERRORS.server };
}

/** false only when fresh Opencast data says nothing is scheduled today for
 *  this recorder; without Opencast or with stale sync data no claim is made. */
export function recordingScheduled(r: Recorder, opencastEnabled: boolean, opencastStale: boolean): boolean {
  return !(opencastEnabled && !opencastStale && !r.current_event && !r.next_event);
}

/** The Opencast schedule cannot back a "nothing scheduled" claim: the data is
 *  stale, or the sync works but Opencast shows no events at all (likely
 *  missing permissions). Pass the result as `opencastStale` to
 *  `recordingScheduled`. */
export function scheduleUnclear(opencastStale: boolean, errorKind: string): boolean {
  return opencastStale || errorKind === "no_events";
}

/** Whole minutes since the stream went missing, never negative. */
export function missingMinutes(sinceIso: string, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(sinceIso).getTime()) / 60000));
}

/** Recorders that are "missing" now but were not in `prev` (ids of the last
 *  poll's missing recorders). `prev === null` is the first load: nothing is
 *  announced then. */
export function newlyMissing(prev: ReadonlySet<number> | null, list: Recorder[]): Recorder[] {
  if (prev === null) return [];
  return list.filter((r) => presentation(r) === "missing" && !prev.has(r.id));
}

/** "No recording today" line: quiet recorders except "unknown" ones, which
 *  are listed apart as "Status unknown" and never as "no recording". */
export function quietWithoutRecording(list: Recorder[]): Recorder[] {
  return quietToday(list).filter((r) => presentation(r) !== "unknown");
}

export const AGENT_STATES = ["idle", "capturing", "uploading", "offline", "unknown"] as const;
export type AgentState = (typeof AGENT_STATES)[number];

/** The agent state if it has a translation; null for "" (never seen) or any
 *  other value (shown raw). Case-sensitive, never normalised. */
export function knownAgentState(state: string): AgentState | null {
  return (AGENT_STATES as readonly string[]).includes(state) ? (state as AgentState) : null;
}

/** Admin list order: "new – please check" first, then by display name. */
export function sortForAdmin(list: Recorder[]): Recorder[] {
  return [...list].sort((a, b) => {
    const d = Number(b.needs_review) - Number(a.needs_review);
    if (d !== 0) return d;
    return displayName(a).localeCompare(displayName(b), "de", { numeric: true });
  });
}

export function hasLastRecordingProblems(r: Recorder): boolean {
  return !!r.last_recording && r.last_recording.problems.length > 0;
}

export type ProblemText = { key: string; params: Record<string, string | number> };

/** Texts for the problems of the last recording: literal i18n keys (so
 *  check:i18n sees them) plus their interpolation params. Kinds this client
 *  does not know (newer backend) are skipped. */
export function problemTexts(
  lr: LastRecording | null,
  locale: string,
): ProblemText[] {
  if (!lr) return [];
  return lr.problems.flatMap((p): ProblemText[] => {
    switch (p.kind) {
      case "stream_missing":
        return [{
          key: "Stream missing {{from}}–{{to}} ({{minutes}} min)",
          params: {
            from: p.from ? formatClock(p.from, locale) : "",
            to: p.to ? formatClock(p.to, locale) : "",
            minutes: p.minutes ?? 0,
          },
        }];
      case "processing_failed":
        return [{ key: "Processing in Opencast failed", params: {} }];
      case "recording_failed":
        return [{ key: "Recording failed on the recorder", params: {} }];
      case "not_started":
        return [{ key: "Recording did not start", params: {} }];
      case "not_finished":
        return [{ key: "Recording did not finish", params: {} }];
      default:
        return [];
    }
  });
}

/** Params for "{{title}}, {{day}} {{from}}–{{to}}": short weekday + date. */
export function lastRecordingRef(lr: LastRecording, locale: string): Record<string, string> {
  return {
    title: lr.title,
    day: new Date(lr.start).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "numeric" }),
    from: formatClock(lr.start, locale),
    to: formatClock(lr.end, locale),
  };
}
