// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Pure level maths for the audio meter. */

export type LevelDescription = "silent" | "low" | "normal";

/** RMS of the samples in dBFS; silence gives -Infinity. */
export function rmsToDbfs(samples: Float32Array): number {
  if (samples.length === 0) return -Infinity;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / samples.length);
  return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
}

/** -60 dBFS -> 0, 0 dBFS -> 1, clamped. */
export function dbfsToMeter(db: number): number {
  if (!Number.isFinite(db)) return db > 0 ? 1 : 0;
  return Math.min(1, Math.max(0, (db + 60) / 60));
}

export function describeLevel(db: number): LevelDescription {
  if (db < -50) return "silent";
  if (db < -30) return "low";
  return "normal";
}
