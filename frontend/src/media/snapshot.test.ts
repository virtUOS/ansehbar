// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import { captureFrame, snapshotSize } from "./snapshot";

describe("snapshotSize", () => {
  it("returns null for zero dimensions", () => {
    expect(snapshotSize(0, 0)).toBeNull();
  });
  it("keeps small frames", () => {
    expect(snapshotSize(1280, 720)).toEqual({ width: 1280, height: 720 });
  });
  it("scales down to max width", () => {
    expect(snapshotSize(3840, 2160)).toEqual({ width: 1920, height: 1080 });
    expect(snapshotSize(1000, 333, 500)).toEqual({ width: 500, height: 167 });
  });
});

describe("captureFrame", () => {
  it("returns null without a video", async () => {
    expect(await captureFrame(null)).toBeNull();
  });
});
