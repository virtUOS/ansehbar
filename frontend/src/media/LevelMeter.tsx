// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dbfsToMeter, meterReading, rmsToDbfs, type MeterReading } from "./level";
import { useAudio } from "./AudioContextProvider";

const REDUCED_MOTION_INTERVAL_MS = 250;

export function LevelMeter({ id }: { id: number }) {
  const { t } = useTranslation();
  const { unlocked, analyser, analyserUnavailable, isForceMuted, isPlaying } = useAudio();
  // A force-muted element only feeds silence: never show "silent" for it.
  const forced = isForceMuted(id);
  const node = unlocked && !forced ? analyser(id) : null;
  const fill = useRef<HTMLDivElement>(null);
  const meter = useRef<HTMLDivElement>(null);
  // Starts "unavailable": nothing is known before the first frame.
  const [level, setLevel] = useState<MeterReading>("unavailable");

  useEffect(() => {
    if (!node) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const buf = new Float32Array(node.fftSize);
    let raf = 0;
    let last = 0;
    let lastDesc: MeterReading | null = null;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (reduced && now - last < REDUCED_MOTION_INTERVAL_MS) return;
      last = now;
      // A stalled element feeds the analyser silence: that is not "silent".
      const playing = isPlaying(id);
      let db = -Infinity;
      if (playing) {
        node.getFloatTimeDomainData(buf);
        db = rmsToDbfs(buf);
      }
      const value = playing ? dbfsToMeter(db) : 0;
      if (fill.current) fill.current.style.height = `${Math.round(value * 100)}%`;
      meter.current?.setAttribute("aria-valuenow", value.toFixed(2));
      const desc = meterReading(playing, db);
      if (desc !== lastDesc) {
        lastDesc = desc;
        setLevel(desc);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [node, id, isPlaying]);

  // "unavailable": native playback, or the element is not really playing;
  // "not yet wired" shows no text.
  const label = !unlocked || forced
    ? t("Level after click")
    : node
      ? level === "unavailable"
        ? t("Level unavailable")
        : t(level)
      : analyserUnavailable(id)
        ? t("Level unavailable")
        : "";

  return (
    <div className="flex items-end" title={label}>
      <div
        ref={meter}
        role="meter"
        aria-label={t("Level")}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={0}
        aria-valuetext={label || t("Level")}
        className="relative h-full min-h-12 w-2.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
      >
        {node ? (
          <div
            ref={fill}
            className="absolute inset-x-0 bottom-0 bg-slate-600 dark:bg-slate-300"
            style={{ height: "0%" }}
          />
        ) : null}
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}
