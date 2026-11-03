// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

// Local-time helpers: run in the app's zone, where summer time ends on
// Sunday, 2026-10-25. Node picks up a TZ change at runtime.
// No @types/node in this project: declare the one global used.
declare const process: { env: Record<string, string | undefined> };
process.env.TZ = "Europe/Berlin";

import { describe, expect, it } from "vitest";
import type { CalendarEvent, IncidentEntry } from "./api";
import { addDays, eventMarkers, groupByDay, isoDay, weekStart } from "./calendar";

function incident(over: Partial<IncidentEntry>): IncidentEntry {
  return {
    id: 1,
    kind: "stream_missing",
    started_at: "2026-11-03T10:10:00Z",
    ended_at: "2026-11-03T10:15:00Z",
    recovered: true,
    alerted_at: null,
    all_clear_at: null,
    silent_until: null,
    ...over,
  };
}

function ev(over: Partial<CalendarEvent>): CalendarEvent {
  return {
    id: 1,
    recorder_id: 1,
    title: "Testvorlesung",
    series: "",
    start: "2026-11-03T10:00:00Z",
    end: "2026-11-03T11:30:00Z",
    opencast_status: "",
    first_audio_at: null,
    incidents: [],
    problems: [],
    ...over,
  };
}

describe("date helpers", () => {
  it("runs in Europe/Berlin", () => {
    expect(new Date(2026, 9, 24, 12).getTimezoneOffset()).toBe(-120);
    expect(new Date(2026, 9, 26, 12).getTimezoneOffset()).toBe(-60);
  });

  it("weekStart of Sunday 2026-10-25 is Monday 2026-10-19", () => {
    expect(isoDay(weekStart(new Date(2026, 9, 25, 18, 0)))).toBe("2026-10-19");
    expect(weekStart(new Date(2026, 9, 25, 18, 0)).getHours()).toBe(0);
  });

  it("weekStart of a Monday is that Monday", () => {
    expect(isoDay(weekStart(new Date(2026, 9, 26, 0, 30)))).toBe("2026-10-26");
  });

  it("addDays crosses the end of summer time", () => {
    expect(isoDay(addDays(new Date(2026, 9, 24), 2))).toBe("2026-10-26");
    expect(addDays(new Date(2026, 9, 24), 2).getHours()).toBe(0);
  });
});

describe("groupByDay", () => {
  it("puts an event over midnight on both days", () => {
    // 23:00–01:00 local (CET, UTC+1).
    const overnight = ev({ id: 7, start: "2026-11-03T22:00:00Z", end: "2026-11-04T00:00:00Z" });
    const days = groupByDay([overnight], new Date(2026, 10, 2), 7);
    expect(days.map((d) => d.day)).toEqual([
      "2026-11-02",
      "2026-11-03",
      "2026-11-04",
      "2026-11-05",
      "2026-11-06",
      "2026-11-07",
      "2026-11-08",
    ]);
    expect(days[1].events.map((e) => e.id)).toEqual([7]);
    expect(days[2].events.map((e) => e.id)).toEqual([7]);
    expect(days[0].events).toEqual([]);
    expect(days[3].events).toEqual([]);
  });

  it("sorts a day's events by start", () => {
    const late = ev({ id: 2, start: "2026-11-03T14:00:00Z", end: "2026-11-03T15:00:00Z" });
    const early = ev({ id: 3, start: "2026-11-03T08:00:00Z", end: "2026-11-03T09:00:00Z" });
    const [day] = groupByDay([late, early], new Date(2026, 10, 3), 1);
    expect(day.events.map((e) => e.id)).toEqual([3, 2]);
  });

  it("puts a Sunday-evening event in the week of the summer-time change on Sunday", () => {
    const sunday = ev({ id: 4, start: "2026-10-25T19:00:00Z", end: "2026-10-25T20:00:00Z" });
    const days = groupByDay([sunday], new Date(2026, 9, 19), 7);
    expect(days[6].day).toBe("2026-10-25");
    expect(days[6].events.map((e) => e.id)).toEqual([4]);
  });
});

describe("eventMarkers", () => {
  const AFTER = new Date("2026-11-03T12:00:00Z");

  it("sums two stream_missing incidents into one marker", () => {
    const markers = eventMarkers(
      ev({
        incidents: [
          incident({ id: 1, started_at: "2026-11-03T10:10:00Z", ended_at: "2026-11-03T10:15:00Z" }),
          incident({ id: 2, started_at: "2026-11-03T10:40:00Z", ended_at: "2026-11-03T10:43:00Z" }),
        ],
      }),
      AFTER,
    );
    expect(markers).toEqual([{ kind: "missing", minutes: 8 }]);
  });

  it("counts an open silence up to silent_until, then now", () => {
    const silent = incident({ kind: "audio_silent", started_at: "2026-11-03T10:20:00Z", ended_at: null });
    const now = new Date("2026-11-03T10:30:00Z");
    expect(eventMarkers(ev({ incidents: [silent] }), now)).toEqual([{ kind: "silent", minutes: 10 }]);
    const until = { ...silent, silent_until: "2026-11-03T10:25:00Z" };
    expect(eventMarkers(ev({ incidents: [until] }), now)).toEqual([{ kind: "silent", minutes: 5 }]);
  });

  it("clamps an open incident of an ended event to the event window", () => {
    const open = incident({ started_at: "2026-11-03T11:00:00Z", ended_at: null });
    // Event ends 11:30 (see ev()); now is much later.
    expect(eventMarkers(ev({ incidents: [open] }), AFTER)).toEqual([{ kind: "missing", minutes: 30 }]);
  });

  it("gives alarm when an incident was alerted", () => {
    const markers = eventMarkers(ev({ incidents: [incident({ alerted_at: "2026-11-03T10:13:00Z" })] }), AFTER);
    expect(markers.map((m) => m.kind)).toEqual(["missing", "alarm"]);
  });

  it("lists Opencast problems that are not incidents", () => {
    const markers = eventMarkers(
      ev({ problems: [{ kind: "processing_failed" }, { kind: "stream_missing", from: "a", to: "b", minutes: 5 }] }),
      AFTER,
    );
    expect(markers).toEqual([{ kind: "problem", problem: { kind: "processing_failed" } }]);
  });

  it("gives clean only for a finished event without incidents and problems", () => {
    expect(eventMarkers(ev({}), AFTER)).toEqual([{ kind: "clean" }]);
    expect(eventMarkers(ev({}), new Date("2026-11-03T11:00:00Z"))).toEqual([]);
    expect(eventMarkers(ev({ problems: [{ kind: "not_finished" }] }), AFTER).map((m) => m.kind)).toEqual(["problem"]);
    expect(eventMarkers(ev({ incidents: [incident({})] }), AFTER).map((m) => m.kind)).toEqual(["missing"]);
  });
});
