// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { formatClock, presentation } from "../recorders";
import { RoomName } from "./RoomName";
import { StatusBadge } from "./StatusBadge";

export function RoomList({ recorders }: { recorders: Recorder[] }) {
  const { t, i18n } = useTranslation();
  const when = (r: Recorder): string | null => {
    const p = presentation(r);
    if (p === "missing") {
      const from = r.current_event?.start ?? r.missing_since;
      return from ? `${t("from")} ${formatClock(from, i18n.language)}` : null;
    }
    if ((p === "live" || p === "live-unknown") && r.status.live_since) {
      return `${t("since")} ${formatClock(r.status.live_since, i18n.language)}`;
    }
    if (r.next_event)
      return t("today from {{time}}", {
        time: formatClock(r.next_event.start, i18n.language),
      });
    return null;
  };
  return (
    <ul className="divide-y divide-slate-200 dark:divide-slate-800">
      {recorders.map((r) => (
        <li key={r.id}>
          <Link
            to={`/raum/${r.id}`}
            className="flex items-center gap-3 px-1 py-3 hover:bg-slate-50 dark:hover:bg-slate-900"
          >
            <span className="shrink-0">
              <StatusBadge
                state={
                  presentation(r) === "missing" ? "missing" : r.status.state
                }
              />
            </span>
            <span className="min-w-0 flex-1 truncate text-lg font-bold">
              <RoomName recorder={r} />
            </span>
            {when(r) ? (
              <span className="shrink-0 text-base font-bold tabular-nums">
                {when(r)}
              </span>
            ) : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}
