// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import type { RecorderState } from "../api";

/** Always text plus symbol, never colour alone. */
const STYLE: Record<RecorderState, { symbol: string; label: string; cls: string }> = {
  live: { symbol: "●", label: "LIVE", cls: "bg-red-700 text-white" },
  offline: {
    symbol: "○",
    label: "No stream",
    cls: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100",
  },
  unknown: { symbol: "?", label: "Status unknown", cls: "bg-amber-300 text-amber-950" },
};

export function StatusBadge({ state }: { state: RecorderState }) {
  const { t } = useTranslation();
  const s = STYLE[state];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold ${s.cls}`}>
      <span aria-hidden>{s.symbol}</span>
      {t(s.label)}
    </span>
  );
}
