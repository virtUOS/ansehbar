// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { formatClock, showTomorrow, untilParts, upcomingToday, upcomingTomorrow } from "../recorders";
import { useNow } from "../useNow";
import { RoomName } from "./RoomName";

/** "Still scheduled today" and, in the evening or when nothing is left
 *  today, "Tomorrow": lists, not tiles. `recorders` are the (filtered) rows;
 *  `allActive` is the unfiltered active list the "show tomorrow" decision
 *  rests on, so a search does not flip it. */
export function UpcomingList({
  recorders,
  allActive = recorders,
}: {
  recorders: Recorder[];
  allActive?: Recorder[];
}) {
  const { t, i18n } = useTranslation();
  const now = useNow(30000);
  const rows = upcomingToday(recorders, now);
  const tomorrowRows = showTomorrow(allActive, now) ? upcomingTomorrow(recorders) : [];
  if (rows.length === 0 && tomorrowRows.length === 0) return null;
  const tomorrowDate = new Date(now.getTime());
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  return (
    <>
      {rows.length > 0 ? (
        <section aria-labelledby="upcoming-heading" className="space-y-2">
          <h2 id="upcoming-heading" className="text-lg font-bold">
            {t("Still scheduled today")}
          </h2>
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {rows.map((r) => {
              const ev = r.next_event!;
              const { hours, minutes } = untilParts(ev.start, now);
              return (
                <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2">
                  <span className="font-bold tabular-nums text-brand-700 dark:text-brand-300">
                    {formatClock(ev.start, i18n.language)}–{formatClock(ev.end, i18n.language)}
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
      ) : null}
      {tomorrowRows.length > 0 ? (
        <section aria-labelledby="tomorrow-heading" className="space-y-2">
          <h2 id="tomorrow-heading" className="text-lg font-bold">
            {t("Tomorrow, {{date}}", {
              date: tomorrowDate.toLocaleDateString(i18n.language, {
                weekday: "long",
                day: "numeric",
                month: "numeric",
              }),
            })}
          </h2>
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {tomorrowRows.map((r) => {
              const ev = r.next_event_tomorrow!;
              return (
                <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2">
                  <span className="font-bold tabular-nums text-brand-700 dark:text-brand-300">
                    {formatClock(ev.start, i18n.language)}–{formatClock(ev.end, i18n.language)}
                  </span>
                  <Link to={`/raum/${r.id}`} className="font-bold hover:underline">
                    <RoomName recorder={r} />
                  </Link>
                  <span className="min-w-0 flex-1 basis-40 truncate text-slate-700 dark:text-slate-300">
                    {ev.title}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </>
  );
}
