// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { describe, expect, it } from "vitest";
import { dbfsToMeter, describeLevel, meterReading, rmsToDbfs, serverReading } from "./level";

describe("level", () => {
  it("rmsToDbfs of full-scale sine is about -3.01", () => {
    const s = new Float32Array(1024).map((_, i) => Math.sin((2 * Math.PI * i * 8) / 1024));
    expect(rmsToDbfs(s)).toBeCloseTo(-3.01, 1);
  });
  it("rmsToDbfs of zeros is -Infinity", () => {
    expect(rmsToDbfs(new Float32Array(64))).toBe(-Infinity);
  });
  it("dbfsToMeter clamps", () => {
    expect(dbfsToMeter(-80)).toBe(0);
    expect(dbfsToMeter(-Infinity)).toBe(0);
    expect(dbfsToMeter(0)).toBe(1);
    expect(dbfsToMeter(6)).toBe(1);
    expect(dbfsToMeter(-30)).toBeCloseTo(0.5);
  });
  it("describeLevel thresholds", () => {
    expect(describeLevel(-55)).toBe("silent");
    expect(describeLevel(-Infinity)).toBe("silent");
    expect(describeLevel(-40)).toBe("low");
    expect(describeLevel(-20)).toBe("normal");
  });
});

describe("meterReading", () => {
  it("not playing is unavailable, never silent", () => {
    expect(meterReading(false, -Infinity)).toBe("unavailable");
    expect(meterReading(false, -10)).toBe("unavailable");
  });
  it("playing describes the level", () => {
    expect(meterReading(true, -Infinity)).toBe("silent");
    expect(meterReading(true, -10)).toBe("normal");
  });
});

describe("serverReading", () => {
  it("is null without a server level", () => {
    expect(serverReading(null)).toBeNull();
    expect(serverReading(undefined)).toBeNull();
  });
  it("maps the server dB to meter value and description", () => {
    expect(serverReading(-35)).toEqual({ value: dbfsToMeter(-35), description: "low" });
    expect(serverReading(-91)).toEqual({ value: 0, description: "silent" });
    expect(serverReading(-20)).toEqual({ value: dbfsToMeter(-20), description: "normal" });
  });
});
