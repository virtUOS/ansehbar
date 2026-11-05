// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Still image of a playing <video> for support tickets. */

/** Target size of the snapshot: proportional, at most `maxWidth` wide, whole pixels. */
export function snapshotSize(
  videoWidth: number,
  videoHeight: number,
  maxWidth = 1920,
): { width: number; height: number } | null {
  if (!(videoWidth > 0) || !(videoHeight > 0)) return null;
  if (videoWidth <= maxWidth) return { width: Math.round(videoWidth), height: Math.round(videoHeight) };
  return { width: maxWidth, height: Math.round((videoHeight * maxWidth) / videoWidth) };
}

/** JPEG of the current video frame, or null when none can be taken
 *  (no video, no picture yet, tainted canvas/SecurityError, …). */
export async function captureFrame(video: HTMLVideoElement | null): Promise<Blob | null> {
  try {
    if (!video) return null;
    const size = snapshotSize(video.videoWidth, video.videoHeight);
    if (!size) return null;
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, size.width, size.height);
    return await new Promise<Blob | null>((resolve) => {
      try {
        canvas.toBlob((b) => resolve(b), "image/jpeg", 0.9);
      } catch {
        resolve(null);
      }
    });
  } catch {
    return null;
  }
}
