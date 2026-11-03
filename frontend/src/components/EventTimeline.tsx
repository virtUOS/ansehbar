// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { formatClock } from "../recorders";
import type { TimelineEntry } from "../timeline";

const SYMBOLS: Record<TimelineEntry["kind"], string> = {
  stable: "✓",
  first_audio: "🔊",
  missing: "⚠",
  missing_open: "⚠",
  silent: "◐",
  silent_open: "◐",
  alarm: "🔔",
  all_clear: "✓",
};

/** Literal t() calls, so check:i18n sees the keys. */
function entryText(t: TFunction, e: TimelineEntry, lang: string): string {
  const time = formatClock(e.at, lang);
  const minutes = e.minutes ?? 1;
  switch (e.kind) {
    case "stable":
      return t("Picture stable since {{time}}", { time });
    case "first_audio":
      return t("First sound at {{time}}", { time });
    case "missing":
      return t("{{time}} Stream missing {{minutes}} min", { time, minutes });
    case "missing_open":
      return t("Stream missing since {{time}}", { time });
    case "silent":
      return t("{{time}} Silent {{minutes}} min (logged)", { time, minutes });
    case "silent_open":
      return t("Silent since {{time}}", { time });
    case "alarm":
      return t("Alarm raised {{time}}", { time });
    case "all_clear":
      return t("All clear sent {{time}}", { time });
  }
}

/** An event's timeline: symbol (decorative) and text per entry, in time order. */
export function EventTimeline({ entries }: { entries: TimelineEntry[] }) {
  const { t, i18n } = useTranslation();
  if (entries.length === 0) {
    return <p className="text-sm text-slate-700 dark:text-slate-300">{t("No incidents")}</p>;
  }
  return (
    <ol className="space-y-1 text-sm text-slate-800 dark:text-slate-100">
      {entries.map((e, i) => (
        <li key={`${e.kind}-${e.at}-${i}`} className="flex items-baseline gap-2">
          <span aria-hidden className="w-5 shrink-0 text-center">
            {SYMBOLS[e.kind]}
          </span>
          <span className="min-w-0 break-words tabular-nums">{entryText(t, e, i18n.language)}</span>
        </li>
      ))}
    </ol>
  );
}
