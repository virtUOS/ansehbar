// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dbfsToMeter, describeLevel, rmsToDbfs, type LevelDescription } from "./level";
import { useAudio } from "./AudioContextProvider";

const REDUCED_MOTION_INTERVAL_MS = 250;

export function LevelMeter({ id }: { id: number }) {
  const { t } = useTranslation();
  const { unlocked, analyser, analyserUnavailable } = useAudio();
  const node = unlocked ? analyser(id) : null;
  const fill = useRef<HTMLDivElement>(null);
  const meter = useRef<HTMLDivElement>(null);
  const [level, setLevel] = useState<LevelDescription>("silent");

  useEffect(() => {
    if (!node) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const buf = new Float32Array(node.fftSize);
    let raf = 0;
    let last = 0;
    let lastDesc: LevelDescription | null = null;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (reduced && now - last < REDUCED_MOTION_INTERVAL_MS) return;
      last = now;
      node.getFloatTimeDomainData(buf);
      const db = rmsToDbfs(buf);
      const value = dbfsToMeter(db);
      if (fill.current) fill.current.style.height = `${Math.round(value * 100)}%`;
      meter.current?.setAttribute("aria-valuenow", value.toFixed(2));
      const desc = describeLevel(db);
      if (desc !== lastDesc) {
        lastDesc = desc;
        setLevel(desc);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [node]);

  // "unavailable" only for native playback; "not yet wired" shows no text.
  const label = !unlocked
    ? t("Level after click")
    : node
      ? t(level)
      : analyserUnavailable(id)
        ? t("Level unavailable")
        : "";

  return (
    <div className="flex items-end gap-1.5" title={label}>
      <div
        ref={meter}
        role="meter"
        aria-label={t("Level")}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={0}
        aria-valuetext={label || t("Level")}
        className="relative h-12 w-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
      >
        {node ? (
          <div
            ref={fill}
            className="absolute inset-x-0 bottom-0 bg-slate-600 dark:bg-slate-300"
            style={{ height: "0%" }}
          />
        ) : null}
      </div>
      <span className="text-xs text-slate-500 dark:text-slate-400">{label}</span>
    </div>
  );
}
