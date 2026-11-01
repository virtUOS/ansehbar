// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { TriangleAlert } from "lucide-react";
import { formatClock } from "../recorders";

/** Shown when the monitor process stopped delivering: statuses are frozen. */
export function MonitorBanner({ stale, lastCheck }: { stale: boolean; lastCheck: string | null }) {
  const { t, i18n } = useTranslation();
  if (!stale) return null;
  return (
    <p
      role="alert"
      className="flex items-center gap-2 rounded-lg border-2 border-amber-500 bg-amber-100 px-3 py-2 font-bold text-amber-950"
    >
      <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
      {t("Monitor has delivered no data since {{time}} – status may be outdated", {
        time: lastCheck ? formatClock(lastCheck, i18n.language) : "–",
      })}
    </p>
  );
}
