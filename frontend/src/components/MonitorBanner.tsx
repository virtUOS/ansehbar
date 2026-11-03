// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Info, TriangleAlert } from "lucide-react";
import { SyncNowButton } from "./SyncNowButton";
import { formatClock, OPENCAST_INSECURE, type OpencastNotice } from "../recorders";
import { opencastNoticeText } from "../opencastTexts";

/** Shown when the monitor process stopped delivering (statuses are frozen),
 *  and, independently, for Opencast: the immediate sync error or hint, else
 *  "out of date". Opencast shows at most one message, with a sync button
 *  (the sync only reads from Opencast). */
export function MonitorBanner({
  stale,
  lastCheck,
  opencastStale = false,
  opencastLastSuccess = null,
  opencastNotice = { level: null, key: null },
  opencastRequested = false,
}: {
  stale: boolean;
  lastCheck: string | null;
  opencastStale?: boolean;
  opencastLastSuccess?: string | null;
  opencastNotice?: OpencastNotice;
  opencastRequested?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const showNotice = opencastNotice.level !== null;
  if (!stale && !opencastStale && !showNotice) return null;
  const box =
    "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border-2 border-amber-500 bg-amber-100 px-3 py-2 font-bold text-amber-950";
  const syncButton = (
    <SyncNowButton
      requested={opencastRequested}
      className="rounded-full bg-white px-3 py-1 text-sm font-bold text-amber-950 ring-1 ring-amber-700 hover:bg-amber-50 disabled:opacity-70"
    />
  );
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
      {showNotice ? (
        <div role="status" className={box}>
          {opencastNotice.level === "hint" ? (
            <Info aria-hidden className="h-5 w-5 shrink-0" />
          ) : (
            <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
          )}
          <span className="min-w-0 flex-1">{opencastNoticeText(t, opencastNotice.key)}</span>
          {/* Syncing cannot help against a refused URL (the server says 409). */}
          {opencastNotice.key === OPENCAST_INSECURE ? null : syncButton}
        </div>
      ) : opencastStale ? (
        <div role="status" className={box}>
          <TriangleAlert aria-hidden className="h-5 w-5 shrink-0" />
          <span className="min-w-0 flex-1">
            {opencastLastSuccess
              ? t("Opencast data out of date – last update {{time}}", {
                  time: formatClock(opencastLastSuccess, i18n.language),
                })
              : t("Opencast data not available yet")}
          </span>
          {syncButton}
        </div>
      ) : null}
    </div>
  );
}
