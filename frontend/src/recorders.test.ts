// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import type { Recorder } from "./api";
import {
  emptyNowMessage,
  filterOverview,
  formatDuration,
  keepsPlayer,
  mergeRecorders,
  monitorStale,
  outsideNow,
  presentation,
  sortForOverview,
  stateTransition,
} from "./recorders";

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
      rec(5, "40/128"),
    ];
    // Digits sort before letters; numbers compare numerically.
    expect(sortForOverview(list).map((r) => r.room_name)).toEqual([
      "90/R12",
      "40/128",
      "40/R05",
      "40/R22",
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

describe("filterOverview", () => {
  const list = [
    { ...rec(1, "40/R05", "live"), stream_name: "cap-90-r12" },
    { ...rec(2, "40/R06", "offline"), stream_name: "cap-90-r13" },
    { ...rec(3, "20/R17", "live"), stream_name: "rec-40/r17" },
  ];
  it("now mode keeps only live recorders matching room or stream, case-insensitively", () => {
    expect(filterOverview(list, "now", "40/r").map((r) => r.id)).toEqual([1, 3]);
  });
  it("all mode includes non-live recorders", () => {
    expect(filterOverview(list, "all", "40/r").map((r) => r.id)).toEqual([1, 2, 3]);
  });
  it("matches stream names and empty query matches everything", () => {
    expect(filterOverview(list, "all", "R13").map((r) => r.id)).toEqual([2]);
    expect(filterOverview(list, "now", "  ").map((r) => r.id)).toEqual([1, 3]);
  });
});

describe("stateTransition", () => {
  it("announces only live<->offline changes after the first load", () => {
    expect(stateTransition(undefined, "live")).toBeNull();
    expect(stateTransition("live", "live")).toBeNull();
    expect(stateTransition("offline", "live")).toBe("started");
    expect(stateTransition("unknown", "live")).toBeNull();
    expect(stateTransition("live", "offline")).toBe("ended");
    expect(stateTransition("live", "unknown")).toBeNull();
  });
});

function withSince(r: Recorder, since: string | null): Recorder {
  return { ...r, status: { ...r.status, live_since: since } };
}

describe("presentation of unknown", () => {
  const since = "2026-01-01T10:00:00Z";
  const liveUnknown = withSince(rec(1, "40/R05", "unknown"), since);
  const unknown = rec(2, "40/R06", "unknown");
  const offline = rec(3, "40/R07", "offline");
  const live = rec(4, "20/R17", "live");
  const inactive = { ...rec(5, "20/R18", "unknown"), active: false };

  it("classifies every case", () => {
    expect(presentation(live)).toBe("live");
    expect(presentation(liveUnknown)).toBe("live-unknown");
    expect(presentation(unknown)).toBe("unknown");
    expect(presentation(offline)).toBe("offline");
    expect(presentation(inactive)).toBe("inactive");
  });

  it("keeps the player for live and unknown-with-live_since only", () => {
    expect([live, liveUnknown, unknown, offline, inactive].map(keepsPlayer)).toEqual([
      true, true, false, false, false,
    ]);
  });

  it("now mode keeps unknown rooms that were last seen live", () => {
    const list = [live, liveUnknown, unknown, offline];
    expect(filterOverview(list, "now", "").map((r) => r.id)).toEqual([4, 1]);
  });

  it("sorts unknown-but-last-live with the live rooms", () => {
    expect(sortForOverview([unknown, offline, liveUnknown]).map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("lists plain unknown separately from offline", () => {
    const { offline: off, unknown: unk } = outsideNow([live, liveUnknown, unknown, offline]);
    expect(off.map((r) => r.id)).toEqual([3]);
    expect(unk.map((r) => r.id)).toEqual([2]);
  });

  it("never claims nothing streams while an active recorder is unknown", () => {
    expect(emptyNowMessage([offline, unknown])).toBe("unclear");
    expect(emptyNowMessage([offline])).toBe("none-streaming");
    expect(emptyNowMessage([offline, inactive])).toBe("none-streaming");
  });
});

describe("monitorStale", () => {
  const now = "2026-01-01T12:00:00Z";
  it("is fresh within three intervals (server clock)", () => {
    expect(monitorStale({ now, last_check: "2026-01-01T11:59:30Z", interval_seconds: 10 }, true)).toBe(false);
  });
  it("is stale beyond three intervals", () => {
    expect(monitorStale({ now, last_check: "2026-01-01T11:59:29Z", interval_seconds: 10 }, true)).toBe(true);
  });
  it("is stale without any check only while active recorders exist", () => {
    expect(monitorStale({ now, last_check: null, interval_seconds: 10 }, true)).toBe(true);
    expect(monitorStale({ now, last_check: null, interval_seconds: 10 }, false)).toBe(false);
  });
});
