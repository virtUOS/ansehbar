// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import type { Recorder } from "./api";
import { formatDuration, mergeRecorders, sortForOverview } from "./recorders";

function rec(id: number, room: string, state: Recorder["status"]["state"] = "offline"): Recorder {
  return {
    id,
    room_name: room,
    stream_name: `cap-${id}`,
    active: true,
    needs_review: false,
    playback_url: "",
    status: { state, live_since: null, checked_at: null },
  };
}

describe("mergeRecorders", () => {
  it("keeps identity of unchanged items", () => {
    const prev = [rec(1, "40/R22"), rec(2, "40/R05")];
    const next = [rec(1, "40/R22"), rec(2, "40/R05")];
    const merged = mergeRecorders(prev, next);
    expect(merged[0]).toBe(prev[0]);
    expect(merged[1]).toBe(prev[1]);
  });

  it("returns the previous array when nothing changed", () => {
    const prev = [rec(1, "40/R22"), rec(2, "40/R05")];
    expect(mergeRecorders(prev, [rec(1, "40/R22"), rec(2, "40/R05")])).toBe(prev);
  });

  it("replaces changed status", () => {
    const prev = [rec(1, "40/R22"), rec(2, "40/R05")];
    const next = [rec(1, "40/R22", "live"), rec(2, "40/R05")];
    const merged = mergeRecorders(prev, next);
    expect(merged[0]).not.toBe(prev[0]);
    expect(merged[0].status.state).toBe("live");
    expect(merged[1]).toBe(prev[1]);
  });
});

describe("sortForOverview", () => {
  it("puts live first then numeric room order", () => {
    const list = [
      rec(1, "70/R01"),
      rec(2, "40/R05"),
      rec(3, "90/R12", "live"),
      rec(4, "40/R22"),
    ];
    expect(sortForOverview(list).map((r) => r.room_name)).toEqual([
      "90/R12",
      "40/R22",
      "40/R05",
      "70/R01",
    ]);
  });
});

describe("formatDuration", () => {
  const now = new Date("2026-01-01T12:00:00Z");
  it("formats minutes and seconds", () => {
    expect(formatDuration("2026-01-01T11:12:48Z", now)).toBe("47:12");
  });
  it("formats hours", () => {
    expect(formatDuration("2026-01-01T10:12:48Z", now)).toBe("1:47:12");
  });
});
