// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import type { EventDetail } from "../api";
import { formatClock } from "../recorders";
import { levelCurve } from "../timeline";

const W = 600;
const H = 100;

/** The event's measured level as an SVG curve over its duration (0 dBFS top,
 *  −70 dBFS bottom); the silence threshold is a dashed line, so it does not
 *  rely on colour. */
export function LevelCurve({ detail }: { detail: EventDetail }) {
  const { t, i18n } = useTranslation();
  if (detail.samples.length === 0) {
    return <p className="text-sm text-slate-700 dark:text-slate-300">{t("No level measurements")}</p>;
  }
  const { segments, thresholdY, silentCount } = levelCurve(detail.samples, detail.start, detail.end, detail.threshold_db, W, H);
  const label = t("Level curve: {{count}} measurements, {{silent}} below the threshold", {
    count: detail.samples.length,
    silent: silentCount,
  });
  return (
    <figure className="space-y-1">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-24 w-full rounded-lg bg-slate-100 dark:bg-slate-800"
      >
        <line
          x1={0}
          x2={W}
          y1={thresholdY}
          y2={thresholdY}
          strokeDasharray="6 4"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          className="stroke-slate-500 dark:stroke-slate-400"
        />
        {segments.map((seg, i) => {
          // A lone sample is drawn as a short dash, so it stays visible.
          const pts = seg.length === 1 ? [{ x: seg[0].x - 1, y: seg[0].y }, { x: seg[0].x + 1, y: seg[0].y }] : seg;
          return (
            <polyline
              key={i}
              points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
              fill="none"
              strokeWidth={2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              className="stroke-slate-800 dark:stroke-slate-200"
            />
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap justify-between gap-x-3 text-xs tabular-nums text-slate-700 dark:text-slate-300">
        <span>{formatClock(detail.start, i18n.language)}</span>
        <span>
          <span aria-hidden>- - </span>
          {t("Silence threshold {{db}} dBFS", { db: detail.threshold_db })}
        </span>
        <span>{formatClock(detail.end, i18n.language)}</span>
      </figcaption>
    </figure>
  );
}
