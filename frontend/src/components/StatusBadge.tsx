// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import type { RecorderState } from "../api";

/** Always text plus symbol, never colour alone. */
type BadgeState = RecorderState | "inactive" | "missing";

const STYLE: Record<
  BadgeState,
  { symbol: string; label: string; cls: string }
> = {
  live: { symbol: "●", label: "LIVE", cls: "bg-red-700 text-white" },
  offline: {
    symbol: "○",
    label: "No stream",
    cls: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100",
  },
  unknown: {
    symbol: "?",
    label: "Status unknown",
    cls: "bg-amber-300 text-amber-950",
  },
  missing: {
    symbol: "⚠",
    label: "Stream missing",
    cls: "bg-red-100 text-red-950 ring-1 ring-red-700 dark:bg-red-950 dark:text-red-100",
  },
  inactive: {
    symbol: "–",
    label: "Recorder inactive",
    cls: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100",
  },
};

export function StatusBadge({ state }: { state: BadgeState }) {
  const { t } = useTranslation();
  const s = STYLE[state];
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-bold ${s.cls}`}
    >
      <span aria-hidden>{s.symbol}</span>
      {t(s.label)}
    </span>
  );
}
