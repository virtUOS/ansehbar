// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import type { EventBrief, MonitorHealth, Recorder } from "./api";
import {
  displayName,
  knownAgentState,
  sortForAdmin,
  emptyNowMessage,
  filterOverview,
  formatDuration,
  keepsPlayer,
  mergeRecorders,
  missingMinutes,
  newlyMissing,
  quietWithoutRecording,
  monitorStale,
  opencastNotice,
  opencastStale,
  outsideNow,
  presentation,
  quietToday,
  recordingScheduled,
  scheduleUnclear,
  roomNameMissing,
  sortForOverview,
  stateTransition,
  untilParts,
  upcomingToday,
} from "./recorders";

function rec(id: number, room: string, state: Recorder["status"]["state"] = "offline"): Recorder {
  return {
    id,
    room_name: room,
    stream_name: `cap-${id}`,
    agent_id: null,
    active: true,
    needs_review: false,
    playback_url: "",
    status: { state, live_since: null, checked_at: null, agent_state: "", agent_updated_at: null },
    current_event: null,
    next_event: null,
    missing_since: null,
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
  const oc = { enabled: false, last_success: null, sync_seconds: 60, last_attempt: null, error_kind: "", requested: false };
  it("is fresh within three intervals (server clock)", () => {
    expect(monitorStale({ now, last_check: "2026-01-01T11:59:30Z", interval_seconds: 10, opencast: oc }, true)).toBe(false);
  });
  it("is stale beyond three intervals", () => {
    expect(monitorStale({ now, last_check: "2026-01-01T11:59:29Z", interval_seconds: 10, opencast: oc }, true)).toBe(true);
  });
  it("is stale without any check only while active recorders exist", () => {
    expect(monitorStale({ now, last_check: null, interval_seconds: 10, opencast: oc }, true)).toBe(true);
    expect(monitorStale({ now, last_check: null, interval_seconds: 10, opencast: oc }, false)).toBe(false);
  });
});

const ev = (title: string, start: string): EventBrief => ({
  title,
  series: "",
  start,
  end: "2026-01-01T14:00:00Z",
});
const missing = (r: Recorder): Recorder => ({ ...r, missing_since: "2026-01-01T10:00:00Z" });

describe("missing presentation", () => {
  it("is missing only for active offline recorders with missing_since", () => {
    expect(presentation(missing(rec(1, "A")))).toBe("missing");
    expect(presentation(missing(rec(1, "A", "unknown")))).toBe("unknown");
    expect(presentation({ ...missing(rec(1, "A")), active: false })).toBe("inactive");
  });
  it("sorts missing before live before offline", () => {
    const list = [rec(1, "A"), rec(2, "B", "live"), missing(rec(3, "C"))];
    expect(sortForOverview(list).map((r) => r.id)).toEqual([3, 2, 1]);
  });
  it("now mode includes missing recorders", () => {
    const list = [rec(1, "A"), missing(rec(2, "B")), rec(3, "C", "live")];
    expect(filterOverview(list, "now", "").map((r) => r.id)).toEqual([2, 3]);
  });
});

describe("today mode, search and event helpers", () => {
  const withNext = { ...rec(1, "A"), next_event: ev("Lecture", "2026-01-01T13:00:00Z") };
  const earlier = { ...rec(2, "B"), next_event: ev("Seminar", "2026-01-01T12:30:00Z") };
  const quiet = rec(3, "C");
  const inactive = { ...rec(4, "D"), active: false, next_event: ev("X", "2026-01-01T12:10:00Z") };
  const now = new Date("2026-01-01T12:00:00Z");

  it("today keeps recorders with events and drops quiet ones", () => {
    expect(filterOverview([withNext, quiet], "today", "").map((r) => r.id)).toEqual([1]);
  });
  it("search matches agent_id", () => {
    const r = { ...rec(5, "E"), agent_id: "rec-hall" };
    expect(filterOverview([r, quiet], "all", "REC-HALL").map((x) => x.id)).toEqual([5]);
  });
  it("upcomingToday sorts by start and skips inactive", () => {
    expect(upcomingToday([withNext, earlier, quiet, inactive], now).map((r) => r.id)).toEqual([2, 1]);
  });
  it("quietToday lists active recorders without events", () => {
    expect(quietToday([withNext, quiet, inactive]).map((r) => r.id)).toEqual([3]);
  });
  it("displayName and roomNameMissing", () => {
    const blank = { ...rec(6, "  "), agent_id: "cap-90-R12" };
    expect(displayName(blank)).toBe("cap-90-R12");
    expect(roomNameMissing(blank)).toBe(true);
    expect(displayName({ ...rec(7, " "), agent_id: null })).toBe("cap-7");
    expect(displayName(rec(8, " 40/R05 "))).toBe("40/R05");
    expect(roomNameMissing(rec(8, "40/R05"))).toBe(false);
  });
  it("untilParts floors to minutes and never goes negative", () => {
    expect(untilParts("2026-01-01T12:43:00Z", new Date("2026-01-01T11:00:00Z"))).toEqual({ hours: 1, minutes: 43 });
    expect(untilParts("2026-01-01T10:00:00Z", now)).toEqual({ hours: 0, minutes: 0 });
  });
  it("merge detects a changed next_event title", () => {
    const prev = [withNext];
    const same = mergeRecorders(prev, [{ ...withNext, next_event: { ...withNext.next_event! } }]);
    expect(same).toBe(prev);
    const changed = mergeRecorders(prev, [{ ...withNext, next_event: ev("Other", "2026-01-01T13:00:00Z") }]);
    expect(changed[0]).not.toBe(prev[0]);
  });
});

describe("opencastStale", () => {
  const h = (enabled: boolean, last_success: string | null): MonitorHealth => ({
    last_check: null,
    now: "2026-01-01T12:00:00Z",
    interval_seconds: 10,
    opencast: { enabled, last_success, sync_seconds: 60, last_attempt: null, error_kind: "", requested: false },
  });
  it("is false when disabled, true without success", () => {
    expect(opencastStale(h(false, null))).toBe(false);
    expect(opencastStale(h(true, null))).toBe(true);
  });
  it("is stale beyond three sync intervals", () => {
    expect(opencastStale(h(true, "2026-01-01T11:57:00Z"))).toBe(false);
    expect(opencastStale(h(true, "2026-01-01T11:56:59Z"))).toBe(true);
  });
});

describe("recordingScheduled", () => {
  it("claims 'nothing scheduled' only with fresh Opencast data", () => {
    const r = rec(1, "A");
    const e = ev("T", "2026-01-01T13:00:00Z");
    expect(recordingScheduled(r, true, false)).toBe(false);
    expect(recordingScheduled(r, true, true)).toBe(true);
    expect(recordingScheduled(r, false, false)).toBe(true);
    expect(recordingScheduled({ ...r, next_event: e }, true, false)).toBe(true);
    expect(recordingScheduled({ ...r, current_event: e }, true, false)).toBe(true);
  });

  it("makes no claim when Opencast shows no events at all", () => {
    const r = rec(1, "A");
    expect(scheduleUnclear(false, "")).toBe(false);
    expect(scheduleUnclear(false, "server")).toBe(false);
    expect(scheduleUnclear(true, "")).toBe(true);
    expect(scheduleUnclear(false, "no_events")).toBe(true);
    expect(recordingScheduled(r, true, scheduleUnclear(false, "no_events"))).toBe(true);
    expect(recordingScheduled(r, true, scheduleUnclear(false, ""))).toBe(false);
  });
});

describe("Stream-missing helpers", () => {
  const miss = (id: number) => ({ ...rec(id, `R${id}`), missing_since: "2026-01-01T11:00:00Z" });
  it("missingMinutes floors and never goes negative", () => {
    expect(missingMinutes("2026-01-01T11:00:00Z", new Date("2026-01-01T11:17:59Z"))).toBe(17);
    expect(missingMinutes("2026-01-01T12:00:00Z", new Date("2026-01-01T11:00:00Z"))).toBe(0);
  });
  it("newlyMissing announces nothing on first load", () => {
    expect(newlyMissing(null, [miss(1)])).toEqual([]);
  });
  it("newlyMissing returns only recorders that were not missing before", () => {
    const list = [miss(1), miss(2), rec(3, "R3")];
    expect(newlyMissing(new Set([1]), list).map((r) => r.id)).toEqual([2]);
  });
  it("quietWithoutRecording drops unknown recorders", () => {
    const list = [rec(1, "A"), rec(2, "B", "unknown")];
    expect(quietToday(list).map((r) => r.id)).toEqual([1, 2]);
    expect(quietWithoutRecording(list).map((r) => r.id)).toEqual([1]);
  });
});

describe("knownAgentState", () => {
  it("knows the translated states only", () => {
    expect(knownAgentState("capturing")).toBe("capturing");
    expect(knownAgentState("")).toBeNull();
    expect(knownAgentState("Idle")).toBeNull();
    expect(knownAgentState("shutting_down")).toBeNull();
  });
});

describe("sortForAdmin", () => {
  it("puts needs_review first, then sorts by display name", () => {
    const b = rec(1, "B room");
    const a = rec(2, "A room");
    const n = { ...rec(3, "Z room"), needs_review: true };
    expect(sortForAdmin([b, a, n]).map((r) => r.id)).toEqual([3, 2, 1]);
  });
  it("does not mutate the input", () => {
    const list = [rec(1, "B"), rec(2, "A")];
    sortForAdmin(list);
    expect(list.map((r) => r.id)).toEqual([1, 2]);
  });
});

describe("opencastNotice", () => {
  const h = (enabled: boolean, error_kind: string): MonitorHealth => ({
    last_check: null,
    now: "2026-01-01T12:00:00Z",
    interval_seconds: 10,
    opencast: { enabled, last_success: null, sync_seconds: 60, last_attempt: null, error_kind, requested: false },
  });
  it("is empty without an error", () => {
    expect(opencastNotice(h(true, ""))).toEqual({ level: null, key: null });
  });
  it("is empty when Opencast is disabled", () => {
    expect(opencastNotice(h(false, "unreachable"))).toEqual({ level: null, key: null });
  });
  it.each([
    ["unreachable", "Opencast not reachable"],
    ["auth", "Opencast rejected the login"],
    ["forbidden", "No permission in Opencast"],
    ["timeout", "Opencast did not answer in time"],
    ["server", "Opencast server error"],
    ["invalid", "Unexpected answer from Opencast"],
  ])("maps %s to an error", (kind, key) => {
    expect(opencastNotice(h(true, kind))).toEqual({ level: "error", key });
  });
  it("maps no_events to a hint", () => {
    expect(opencastNotice(h(true, "no_events"))).toEqual({
      level: "hint",
      key: "Opencast shows no scheduled recordings – check the account's permissions",
    });
  });
  it("treats an unknown kind as a generic server error", () => {
    expect(opencastNotice(h(true, "weird"))).toEqual({ level: "error", key: "Opencast server error" });
  });
});
