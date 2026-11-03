// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import type { IncidentEntry, LevelSample } from "./api";
import { levelCurve, timelineEntries } from "./timeline";

const START = "2026-11-03T10:00:00Z";
const END = "2026-11-03T11:30:00Z";
const NOW = new Date("2026-11-03T10:45:00Z");

function at(minutes: number, seconds = 0): string {
  return new Date(Date.parse(START) + minutes * 60_000 + seconds * 1000).toISOString();
}

function incident(over: Partial<IncidentEntry>): IncidentEntry {
  return {
    id: 1,
    kind: "stream_missing",
    started_at: at(10),
    ended_at: null,
    recovered: false,
    alerted_at: null,
    all_clear_at: null,
    silent_until: null,
    ...over,
  };
}

function ev(incidents: IncidentEntry[], first_audio_at: string | null = null) {
  return { start: START, end: END, first_audio_at, incidents };
}

describe("timelineEntries", () => {
  it("open stream_missing gives missing_open and no stable", () => {
    const entries = timelineEntries(ev([incident({})]), NOW, at(-5));
    expect(entries.map((e) => e.kind)).toEqual(["missing_open"]);
    expect(entries[0].at).toBe(at(10));
  });

  it("live without incidents gives stable at max(liveSince, start)", () => {
    expect(timelineEntries(ev([]), NOW, at(-5))).toEqual([{ kind: "stable", at: START }]);
    expect(timelineEntries(ev([]), NOW, at(3))).toEqual([{ kind: "stable", at: at(3) }]);
  });

  it("no stable without liveSince", () => {
    expect(timelineEntries(ev([]), NOW, null)).toEqual([]);
  });

  it("first_audio entry", () => {
    expect(timelineEntries(ev([], at(2)), NOW, null)).toEqual([{ kind: "first_audio", at: at(2) }]);
  });

  it("finished stream_missing gives missing with minutes", () => {
    const entries = timelineEntries(ev([incident({ ended_at: at(16), recovered: true })]), NOW, null);
    expect(entries).toEqual([{ kind: "missing", at: at(10), minutes: 6 }]);
  });

  it("audio_silent open gives silent_open, finished gives silent with 4 min", () => {
    const open = incident({ kind: "audio_silent", started_at: at(0), silent_until: at(4) });
    expect(timelineEntries(ev([open]), NOW, null)).toEqual([{ kind: "silent_open", at: at(0) }]);
    const done = incident({ kind: "audio_silent", started_at: at(0), ended_at: at(4) });
    expect(timelineEntries(ev([done]), NOW, null)).toEqual([{ kind: "silent", at: at(0), minutes: 4 }]);
  });

  it("silence with ended_at null stays open even with silent_until", () => {
    const done = incident({ kind: "audio_silent", started_at: at(0), recovered: true, silent_until: at(4) });
    // ended_at null means open; only ended_at closes it.
    expect(timelineEntries(ev([done]), NOW, null)[0].kind).toBe("silent_open");
  });

  it("alarm and all_clear entries at their times", () => {
    const inc = incident({ ended_at: at(30), alerted_at: at(12), all_clear_at: at(31) });
    const entries = timelineEntries(ev([inc]), NOW, null);
    expect(entries).toEqual([
      { kind: "missing", at: at(10), minutes: 20 },
      { kind: "alarm", at: at(12) },
      { kind: "all_clear", at: at(31) },
    ]);
  });

  it("minutes are at least 1 and entries are sorted by time", () => {
    const short = incident({ id: 2, started_at: at(40), ended_at: at(40, 10) });
    const silent = incident({ id: 3, kind: "audio_silent", started_at: at(5), ended_at: at(7) });
    const entries = timelineEntries(ev([short, silent], at(1)), NOW, at(-1));
    expect(entries).toEqual([
      { kind: "stable", at: START },
      { kind: "first_audio", at: at(1) },
      { kind: "silent", at: at(5), minutes: 2 },
      { kind: "missing", at: at(40), minutes: 1 },
    ]);
  });
});

describe("levelCurve", () => {
  const W = 600;
  const H = 100;
  const s = (sec: number, db: number | null): LevelSample => ({ t: at(0, sec), db });

  it("gap of 121 s splits, 119 s does not", () => {
    expect(levelCurve([s(0, -20), s(121, -20)], START, END, -50, W, H).segments).toHaveLength(2);
    expect(levelCurve([s(0, -20), s(119, -20)], START, END, -50, W, H).segments).toHaveLength(1);
  });

  it("null and -80 lie at the bottom, 0 dBFS at the top", () => {
    const { segments } = levelCurve([s(0, null), s(30, -80), s(60, 0)], START, END, -50, W, H);
    const ys = segments[0].map((p) => p.y);
    expect(ys).toEqual([H, H, 0]);
  });

  it("x spans the event, threshold line at the right height", () => {
    const r = levelCurve([s(0, -35)], START, END, -35, W, H);
    expect(r.segments[0][0]).toEqual({ x: 0, y: H / 2 });
    expect(r.thresholdY).toBe(H / 2);
  });

  it("silentCount counts values below the threshold and null", () => {
    const r = levelCurve([s(0, null), s(30, -60), s(60, -50), s(90, -20)], START, END, -50, W, H);
    expect(r.silentCount).toBe(2);
  });

  it("no samples, no segments", () => {
    expect(levelCurve([], START, END, -50, W, H)).toEqual({ segments: [], thresholdY: H * (50 / 70), silentCount: 0 });
  });
});
