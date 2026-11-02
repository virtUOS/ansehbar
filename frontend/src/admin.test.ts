// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { identifierFor, previewUrl, sortIgnoredAgents, splitErrors, syncWaitDone, toggleActivePayload } from "./admin";

describe("splitErrors", () => {
  it("maps known fields and routes the rest to general", () => {
    const e = new ApiError("x", 400, { stream_name: ["Duplicate"], non_field_errors: ["Bad"] });
    expect(splitErrors(e, ["stream_name"])).toEqual({
      fields: { stream_name: ["Duplicate"] },
      general: ["Bad"],
    });
  });
  it("uses the message when no details exist", () => {
    expect(splitErrors(new ApiError("Forbidden", 403), ["a"]).general).toEqual(["Forbidden"]);
    expect(splitErrors(new Error("net"), []).general).toEqual(["net"]);
  });
});

describe("previewUrl", () => {
  const tpl = "https://h/{stream}/p.m3u8";
  it("keeps stream case", () => {
    expect(previewUrl(tpl, "cap-90-R12")).toBe("https://h/cap-90-R12/p.m3u8");
  });
  it("falls back to example-stream", () => {
    expect(previewUrl(tpl, undefined)).toBe("https://h/example-stream/p.m3u8");
  });
  it("leaves a template without placeholder untouched", () => {
    expect(previewUrl("https://h/x", "a")).toBe("https://h/x");
  });
});

describe("identifierFor", () => {
  it("prefers email", () => {
    expect(identifierFor({ id: 1, username: "u", email: "u@x.de", display_name: "U" })).toBe("u@x.de");
    expect(identifierFor({ id: 1, username: "u", email: "", display_name: "U" })).toBe("u");
  });
});

describe("toggleActivePayload", () => {
  it("deactivating also marks the recorder as checked", () => {
    expect(toggleActivePayload({ active: true })).toEqual({ active: false, needs_review: false });
  });
  it("activating changes only active", () => {
    expect(toggleActivePayload({ active: false })).toEqual({ active: true });
  });
});

describe("sortIgnoredAgents", () => {
  it("lists the newest first without mutating the input", () => {
    const a = { id: 1, agent_id: "A", created_at: "2026-01-01T10:00:00Z", created_by: "x" };
    const b = { id: 2, agent_id: "B", created_at: "2026-02-01T10:00:00Z", created_by: "y" };
    const list = [a, b];
    expect(sortIgnoredAgents(list).map((i) => i.id)).toEqual([2, 1]);
    expect(list[0]).toBe(a);
  });
});

describe("syncWaitDone", () => {
  it("keeps waiting before the request shows up in the heartbeat", () => {
    expect(syncWaitDone({ requested: false, seenRequested: false, elapsedMs: 3000 })).toBe(false);
  });
  it("is done once the request was seen and is cleared again", () => {
    expect(syncWaitDone({ requested: true, seenRequested: true, elapsedMs: 3000 })).toBe(false);
    expect(syncWaitDone({ requested: false, seenRequested: true, elapsedMs: 3000 })).toBe(true);
  });
  it("assumes a very fast sync after 10 s without ever seeing the request", () => {
    expect(syncWaitDone({ requested: false, seenRequested: false, elapsedMs: 10000 })).toBe(true);
  });
  it("gives up after 60 s", () => {
    expect(syncWaitDone({ requested: true, seenRequested: true, elapsedMs: 60000 })).toBe(true);
  });
});
