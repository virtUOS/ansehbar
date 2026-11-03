// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers of the room calendar: local-time days and event markers. */
import type { CalendarEvent, RecordingProblem } from "./api";

/** Local midnight of `d`. */
function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** `d` plus `n` calendar days at local midnight; via setDate, so a day with
 *  a summer-time change still counts as one day. */
export function addDays(d: Date, n: number): Date {
  const r = startOfDay(d);
  r.setDate(r.getDate() + n);
  return r;
}

/** Monday (local midnight) of the week containing `day`. */
export function weekStart(day: Date): Date {
  const offset = (day.getDay() + 6) % 7; // Monday = 0 … Sunday = 6
  return addDays(day, -offset);
}

/** `YYYY-MM-DD` in local time. */
export function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Local midnight of a `YYYY-MM-DD` string; null for anything else. */
export function parseIsoDay(s: string | null): Date | null {
  const m = s ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(s) : null;
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return isoDay(d) === s ? d : null;
}

/** Events per local day from `from` on, `days` days; an event spanning
 *  midnight appears on every day it overlaps. Sorted by start. */
export function groupByDay(
  events: CalendarEvent[],
  from: Date,
  days: number,
): { day: string; events: CalendarEvent[] }[] {
  const sorted = [...events].sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  const result = [];
  for (let i = 0; i < days; i++) {
    const dayStart = addDays(from, i).getTime();
    const dayEnd = addDays(from, i + 1).getTime();
    result.push({
      day: isoDay(addDays(from, i)),
      events: sorted.filter((e) => Date.parse(e.start) < dayEnd && Date.parse(e.end) > dayStart),
    });
  }
  return result;
}

export type Marker = {
  kind: "missing" | "silent" | "alarm" | "problem" | "clean";
  minutes?: number;
  problem?: RecordingProblem;
};

/** Markers of an event card: summed stream gaps and silences (open ones count
 *  up to now), alarm, Opencast problems; "clean" for a finished event without
 *  any of these. Incident problems are left out, the incidents cover them. */
export function eventMarkers(event: CalendarEvent, now: Date): Marker[] {
  const nowMs = now.getTime();
  let missingMs = 0;
  let silentMs = 0;
  let hasMissing = false;
  let hasSilent = false;
  let alarm = false;
  for (const i of event.incidents) {
    const eventStart = Date.parse(event.start);
    const eventEnd = Date.parse(event.end);
    const start = Math.max(Date.parse(i.started_at), eventStart);
    // Count only the part inside the event window.
    const clampEnd = (ms: number) => Math.min(ms, eventEnd);
    if (i.kind === "stream_missing") {
      hasMissing = true;
      missingMs += Math.max(0, clampEnd(i.ended_at ? Date.parse(i.ended_at) : nowMs) - start);
    } else if (i.kind === "audio_silent") {
      hasSilent = true;
      const until = i.ended_at ?? i.silent_until;
      silentMs += Math.max(0, clampEnd(until ? Date.parse(until) : nowMs) - start);
    }
    if (i.alerted_at) alarm = true;
  }
  const minutes = (ms: number) => Math.max(1, Math.round(ms / 60_000));
  const markers: Marker[] = [];
  if (hasMissing) markers.push({ kind: "missing", minutes: minutes(missingMs) });
  if (hasSilent) markers.push({ kind: "silent", minutes: minutes(silentMs) });
  if (alarm) markers.push({ kind: "alarm" });
  for (const p of event.problems) {
    if (p.kind !== "stream_missing" && p.kind !== "audio_silent") markers.push({ kind: "problem", problem: p });
  }
  if (markers.length === 0 && Date.parse(event.end) <= nowMs) markers.push({ kind: "clean" });
  return markers;
}
