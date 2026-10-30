// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { beforeEach, describe, expect, it, vi } from "vitest";
import { AudioEngine, isActuallyPlaying } from "./audio";

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

function mediaEl(over: Partial<{ paused: boolean; ended: boolean; readyState: number }> = {}) {
  return {
    muted: true,
    paused: false,
    ended: false,
    readyState: 4, // HAVE_ENOUGH_DATA
    play: vi.fn(() => Promise.resolve()),
    ...over,
  } as unknown as HTMLVideoElement;
}

describe("playback state for the level meter", () => {
  it("only a reported-playing element with data counts as playing", () => {
    expect(isActuallyPlaying(mediaEl(), "playing")).toBe(true);
    expect(isActuallyPlaying(mediaEl(), "waiting")).toBe(false);
    expect(isActuallyPlaying(mediaEl(), "retrying")).toBe(false);
    expect(isActuallyPlaying(mediaEl(), "failed")).toBe(false);
    expect(isActuallyPlaying(mediaEl(), undefined)).toBe(false);
    expect(isActuallyPlaying(mediaEl({ paused: true }), "playing")).toBe(false);
    expect(isActuallyPlaying(mediaEl({ ended: true }), "playing")).toBe(false);
    expect(isActuallyPlaying(mediaEl({ readyState: 2 }), "playing")).toBe(false); // HAVE_CURRENT_DATA
    expect(isActuallyPlaying(undefined, "playing")).toBe(false);
  });

  it("engine tracks the reported state per id, notifies, and forgets on detach", () => {
    const e = new AudioEngine();
    const el = mediaEl();
    const detach = e.attach(1, el);
    const fn = vi.fn();
    e.subscribe(fn);
    expect(e.isPlaying(1)).toBe(false); // nothing reported yet

    e.setPlaybackState(1, "playing");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(e.isPlaying(1)).toBe(true);
    e.setPlaybackState(1, "playing"); // unchanged: no notify
    expect(fn).toHaveBeenCalledTimes(1);

    // The element stalls without a new report: checked live.
    (el as unknown as { readyState: number }).readyState = 1;
    expect(e.isPlaying(1)).toBe(false);
    (el as unknown as { readyState: number }).readyState = 4;

    e.setPlaybackState(1, "waiting");
    expect(e.isPlaying(1)).toBe(false);
    expect(e.playbackState(1)).toBe("waiting");

    detach();
    expect(e.playbackState(1)).toBeUndefined();
    expect(e.isPlaying(1)).toBe(false);
  });
});
