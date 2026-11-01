// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { TriangleAlert } from "lucide-react";
import { formatClock } from "../recorders";

/** Shown when the monitor process stopped delivering (statuses are frozen),
 *  and, independently, when the Opencast sync is out of date. */
export function MonitorBanner({
  stale,
  lastCheck,
  opencastStale = false,
  opencastLastSuccess = null,
}: {
  stale: boolean;
  lastCheck: string | null;
  opencastStale?: boolean;
  opencastLastSuccess?: string | null;
}) {
  const { t, i18n } = useTranslation();
  if (!stale && !opencastStale) return null;
  const box =
    "flex items-center gap-2 rounded-lg border-2 border-amber-500 bg-amber-100 px-3 py-2 font-bold text-amber-950";
  return (
    <div className="space-y-2">
      {stale ? (
        <p role="alert" className={box}>
          <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
          {t(
            "Monitor has delivered no data since {{time}} – status may be outdated",
            {
              time: lastCheck ? formatClock(lastCheck, i18n.language) : "–",
            },
          )}
        </p>
      ) : null}
      {opencastStale ? (
        <p role="status" className={box}>
          <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
          {opencastLastSuccess
            ? t("Opencast data out of date – last update {{time}}", {
                time: formatClock(opencastLastSuccess, i18n.language),
              })
            : t("Opencast data not available yet")}
        </p>
      ) : null}
    </div>
  );
}
