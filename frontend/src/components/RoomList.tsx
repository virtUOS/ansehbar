// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { formatClock, hasLastRecordingProblems, presentation, showTomorrow } from "../recorders";
import { useNow } from "../useNow";
import { RoomName } from "./RoomName";
import { StatusBadge } from "./StatusBadge";

export function RoomList({ recorders }: { recorders: Recorder[] }) {
  const { t, i18n } = useTranslation();
  const now = useNow(30000);
  const tomorrow = showTomorrow(recorders, now);
  const when = (r: Recorder, p: ReturnType<typeof presentation>): string | null => {
    if (p === "missing") {
      const from = r.current_event?.start ?? r.missing_since;
      return from ? `${t("from")} ${formatClock(from, i18n.language)}` : null;
    }
    if (p === "silent" && r.silent_since) {
      return t("since {{time}}", { time: formatClock(r.silent_since, i18n.language) });
    }
    if ((p === "live" || p === "live-unknown") && r.status.live_since) {
      return `${t("since")} ${formatClock(r.status.live_since, i18n.language)}`;
    }
    if (r.next_event)
      return t("today from {{time}}", {
        time: formatClock(r.next_event.start, i18n.language),
      });
    if (tomorrow && r.next_event_tomorrow)
      return t("tomorrow from {{time}}", {
        time: formatClock(r.next_event_tomorrow.start, i18n.language),
      });
    return null;
  };
  return (
    <ul className="divide-y divide-slate-200 dark:divide-slate-800">
      {recorders.map((r) => {
        const p = presentation(r);
        const time = when(r, p);
        return (
          <li key={r.id}>
            {/* Narrow screens: room name on its own line (it wraps, never
                truncates), badge and time below; from sm on one row. */}
            <Link
              to={`/raum/${r.id}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 py-3 hover:bg-slate-50 sm:flex-nowrap dark:hover:bg-slate-900"
            >
              <span className="shrink-0">
                <StatusBadge state={p === "missing" || p === "silent" ? p : r.status.state} />
              </span>
              <span className="order-first min-w-0 basis-full break-words text-lg font-bold sm:order-none sm:flex-1 sm:basis-0">
                <RoomName recorder={r} />
                {hasLastRecordingProblems(r) ? (
                  <span className="ml-2 whitespace-nowrap text-sm font-semibold text-amber-900 dark:text-amber-200">
                    <span aria-hidden>⚠</span>
                    <span className="sr-only">{t("Last recording had problems")}</span>
                  </span>
                ) : null}
              </span>
              {time ? (
                <span className="shrink-0 text-base font-bold tabular-nums">
                  {time}
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
