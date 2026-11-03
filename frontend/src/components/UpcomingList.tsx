// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Clock } from "lucide-react";
import type { Recorder } from "../api";
import { DEFAULT_SLOTS, formatClock, groupBySlot, showTomorrow, untilParts, type SlotGroup, type SlotRow } from "../recorders";
import { useNow } from "../useNow";
import { RoomName } from "./RoomName";

/** "Still scheduled today" and, in the evening or when nothing is left
 *  today, "Tomorrow": lists grouped by recording slot, not tiles.
 *  `recorders` are the (filtered) rows; `allActive` is the unfiltered active
 *  list the "show tomorrow" decision rests on, so a search does not flip it. */
export function UpcomingList({
  recorders,
  allActive = recorders,
  slotMinutes = DEFAULT_SLOTS.minutes,
  slotOffset = DEFAULT_SLOTS.offset_minutes,
}: {
  recorders: Recorder[];
  allActive?: Recorder[];
  slotMinutes?: number;
  slotOffset?: number;
}) {
  const { t, i18n } = useTranslation();
  const now = useNow(30000);
  const today = useMemo(
    () => groupBySlot(recorders, "today", { minutes: slotMinutes, offset_minutes: slotOffset }),
    [recorders, slotMinutes, slotOffset],
  );
  const tomorrowShown = showTomorrow(allActive, now);
  const tomorrow = useMemo(
    () => (tomorrowShown ? groupBySlot(recorders, "tomorrow", { minutes: slotMinutes, offset_minutes: slotOffset }) : []),
    [tomorrowShown, recorders, slotMinutes, slotOffset],
  );
  if (today.length === 0 && tomorrow.length === 0) return null;
  const tomorrowDate = new Date(now.getTime());
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);
  return (
    <>
      {today.length > 0 ? (
        <section aria-labelledby="upcoming-heading" className="space-y-2">
          <h2 id="upcoming-heading" className="text-lg font-bold">
            {t("Still scheduled today")}
          </h2>
          <SlotGroups groups={today} now={now} />
        </section>
      ) : null}
      {tomorrow.length > 0 ? (
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
          <SlotGroups groups={tomorrow} />
        </section>
      ) : null}
    </>
  );
}

/** One block per slot: the slot's times (with a countdown when `now` is
 *  given), then its rooms; times off the slot are marked with icon and text. */
function SlotGroups({ groups, now }: { groups: SlotGroup[]; now?: Date }) {
  const { t, i18n } = useTranslation();
  const clock = (d: Date | string) => formatClock(typeof d === "string" ? d : d.toISOString(), i18n.language);
  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const first = group.rows[0].event.start;
        const until = now ? untilParts(first, now) : null;
        return (
          <section
            key={group.start.getTime()}
            aria-label={t("Slot {{from}}–{{to}}", { from: clock(group.start), to: clock(group.end) })}
            className="rounded-xl border border-slate-200 dark:border-slate-800"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 border-b border-slate-200 bg-slate-50 px-3 py-1.5 dark:border-slate-800 dark:bg-slate-900">
              <span className="font-bold tabular-nums text-brand-700 dark:text-brand-300">
                {clock(group.start)}–{clock(group.end)}
              </span>
              {until ? (
                <span className="text-sm tabular-nums text-slate-700 dark:text-slate-300">
                  {until.hours > 0
                    ? t("in {{hours}} h {{minutes}} min", until)
                    : t("in {{minutes}} min", { minutes: until.minutes })}
                </span>
              ) : null}
            </div>
            <ul className="divide-y divide-slate-200 px-3 dark:divide-slate-800">
              {group.rows.map((row) => (
                <SlotRowItem key={`${row.recorder.id}-${row.event.start}`} row={row} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function SlotRowItem({ row }: { row: SlotRow }) {
  const { t, i18n } = useTranslation();
  const { recorder, event, startsOff, endsOff } = row;
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2">
      <Link to={`/raum/${recorder.id}`} className="min-w-20 font-bold hover:underline">
        <RoomName recorder={recorder} />
      </Link>
      <span className="min-w-0 flex-1 basis-40 truncate text-slate-700 dark:text-slate-300">{event.title}</span>
      {startsOff || endsOff ? (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-sm tabular-nums text-amber-950 ring-1 ring-amber-600 dark:bg-amber-950 dark:text-amber-100">
          <Clock aria-hidden className="h-4 w-4 shrink-0" />
          <span className={startsOff ? "font-bold underline" : ""}>{formatClock(event.start, i18n.language)}</span>–
          <span className={endsOff ? "font-bold underline" : ""}>{formatClock(event.end, i18n.language)}</span>
          <span className="font-semibold">{t("differs from slot")}</span>
        </span>
      ) : null}
    </li>
  );
}
