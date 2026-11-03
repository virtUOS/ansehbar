// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure helpers for an event's timeline and its level curve. */
import type { IncidentEntry, LevelSample } from "./api";

export type TimelineEntry = {
  kind: "stable" | "first_audio" | "missing" | "missing_open" | "silent" | "silent_open" | "alarm" | "all_clear";
  at: string;
  minutes?: number;
};

type TimelineEvent = {
  start: string;
  end: string;
  first_audio_at: string | null;
  incidents: IncidentEntry[];
};

/** Rounded minutes between two instants, at least 1. */
function minutesBetween(from: string, to: string): number {
  return Math.max(1, Math.round((Date.parse(to) - Date.parse(from)) / 60_000));
}

/** Timeline entries of an event, sorted by time. `liveSince` is the stream's
 *  live start; pass it only while the event runs and the room is live. */
export function timelineEntries(event: TimelineEvent, now: Date, liveSince: string | null): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const running = Date.parse(event.start) <= now.getTime() && now.getTime() < Date.parse(event.end);
  const missingOpen = event.incidents.some((i) => i.kind === "stream_missing" && i.ended_at === null);
  if (liveSince && running && !missingOpen) {
    const at = Date.parse(liveSince) > Date.parse(event.start) ? liveSince : event.start;
    entries.push({ kind: "stable", at });
  }
  if (event.first_audio_at) entries.push({ kind: "first_audio", at: event.first_audio_at });
  for (const i of event.incidents) {
    if (i.kind === "stream_missing") {
      entries.push(
        i.ended_at
          ? { kind: "missing", at: i.started_at, minutes: minutesBetween(i.started_at, i.ended_at) }
          : { kind: "missing_open", at: i.started_at },
      );
    } else if (i.kind === "audio_silent") {
      const until = i.ended_at ?? i.silent_until;
      entries.push(
        i.ended_at && until
          ? { kind: "silent", at: i.started_at, minutes: minutesBetween(i.started_at, until) }
          : { kind: "silent_open", at: i.started_at },
      );
    }
    if (i.alerted_at) entries.push({ kind: "alarm", at: i.alerted_at });
    if (i.all_clear_at) entries.push({ kind: "all_clear", at: i.all_clear_at });
  }
  // Stable sort: equal times keep their insertion order (incident before its alarm).
  return entries.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

export type CurveSegment = { x: number; y: number }[];

/** Lowest drawn level; quieter values and "no audio track" (null) lie here. */
export const CURVE_FLOOR_DB = -70;
/** Samples further apart than this are not connected. */
const MAX_GAP_MS = 120_000;

/** SVG coordinates of the level curve over the event's duration: y from
 *  0 dBFS (top, y = 0) to −70 dBFS (bottom, y = height). */
export function levelCurve(
  samples: LevelSample[],
  start: string,
  end: string,
  thresholdDb: number,
  width: number,
  height: number,
): { segments: CurveSegment[]; thresholdY: number; silentCount: number } {
  const t0 = Date.parse(start);
  const span = Math.max(1, Date.parse(end) - t0);
  const yOf = (db: number | null) => {
    const v = db === null ? CURVE_FLOOR_DB : Math.min(0, Math.max(CURVE_FLOOR_DB, db));
    return (Math.abs(v) / -CURVE_FLOOR_DB) * height;
  };
  const xOf = (t: number) => Math.min(width, Math.max(0, ((t - t0) / span) * width));

  const sorted = [...samples].sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  const segments: CurveSegment[] = [];
  let prev: number | null = null;
  let silentCount = 0;
  for (const s of sorted) {
    const t = Date.parse(s.t);
    if (prev === null || t - prev > MAX_GAP_MS) segments.push([]);
    segments[segments.length - 1].push({ x: xOf(t), y: yOf(s.db) });
    if (s.db === null || s.db < thresholdDb) silentCount += 1;
    prev = t;
  }
  return { segments, thresholdY: yOf(thresholdDb), silentCount };
}
