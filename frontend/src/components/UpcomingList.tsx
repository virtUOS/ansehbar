// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { formatClock, untilParts, upcomingToday } from "../recorders";
import { useNow } from "../useNow";
import { RoomName } from "./RoomName";

/** "Still scheduled today": a list, not tiles. */
export function UpcomingList({ recorders }: { recorders: Recorder[] }) {
  const { t, i18n } = useTranslation();
  const now = useNow(30000);
  const rows = upcomingToday(recorders, now);
  if (rows.length === 0) return null;
  return (
    <section aria-labelledby="upcoming-heading" className="space-y-2">
      <h2 id="upcoming-heading" className="text-lg font-bold">
        {t("Still scheduled today")}
      </h2>
      <ul className="divide-y divide-slate-200 dark:divide-slate-800">
        {rows.map((r) => {
          const ev = r.next_event!;
          const { hours, minutes } = untilParts(ev.start, now);
          return (
            <li
              key={r.id}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2"
            >
              <span className="font-bold tabular-nums text-brand-700 dark:text-brand-300">
                {formatClock(ev.start, i18n.language)}–
                {formatClock(ev.end, i18n.language)}
              </span>
              <Link to={`/raum/${r.id}`} className="font-bold hover:underline">
                <RoomName recorder={r} />
              </Link>
              <span className="min-w-0 flex-1 basis-40 truncate text-slate-700 dark:text-slate-300">
                {ev.title}
              </span>
              <span className="text-sm tabular-nums text-slate-700 dark:text-slate-300">
                {hours > 0
                  ? t("in {{hours}} h {{minutes}} min", { hours, minutes })
                  : t("in {{minutes}} min", { minutes })}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
