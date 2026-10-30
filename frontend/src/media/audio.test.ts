// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { beforeEach, describe, expect, it, vi } from "vitest";
import { AudioEngine } from "./audio";

function node() {
  return { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 0 }, fftSize: 0 };
}
class FakeCtx {
  state = "suspended";
  destination = {};
  onstatechange: (() => void) | null = null;
  resume = vi.fn(async () => {
    this.state = "running";
    this.onstatechange?.();
  });
  createMediaElementSource = vi.fn(() => node());
  createAnalyser = vi.fn(() => node());
  createGain = vi.fn(() => node());
}
function fakeEl(paused = true) {
  return { muted: true, paused, play: vi.fn(() => Promise.resolve()) } as unknown as HTMLVideoElement;
}

beforeEach(() => {
  vi.stubGlobal("window", { AudioContext: FakeCtx });
});

describe("AudioEngine", () => {
  it("bumps the version on subscribe/notify events", () => {
    const e = new AudioEngine();
    const fn = vi.fn();
    e.subscribe(fn);
    const v = e.getVersion();
    e.markForceMuted(1, true);
    expect(e.getVersion()).toBeGreaterThan(v);
    expect(fn).toHaveBeenCalled();
  });

  it("force-muted element needs a click; unlock recovers it synchronously", async () => {
    const e = new AudioEngine();
    const el = fakeEl(true);
    e.attach(1, el);
    await e.unlock();
    // simulate autoplay fallback after unlock
    el.muted = true;
    e.markForceMuted(1, true);
    expect(e.needsUnlock()).toBe(true);
    (el.play as ReturnType<typeof vi.fn>).mockClear();

    const p = e.unlock(); // no await yet: recovery must already have happened
    expect(el.muted).toBe(false);
    expect(el.play).toHaveBeenCalled();
    expect(e.isForceMuted(1)).toBe(false);
    await p;
    expect(e.needsUnlock()).toBe(false);
  });

  it("wires elements attached before unlock and unmutes them in the click", () => {
    const e = new AudioEngine();
    const el = fakeEl();
    e.attach(1, el);
    expect(e.analyser(1)).toBeNull();
    const p = e.unlock();
    expect(el.muted).toBe(false);
    expect(e.analyser(1)).not.toBeNull();
    return p;
  });
});
