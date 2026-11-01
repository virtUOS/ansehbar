// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { identifierFor, previewUrl, splitErrors } from "./admin";

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
