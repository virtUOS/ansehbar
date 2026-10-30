// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { formatClock, keepsPlayer } from "../recorders";
import { StatusBadge } from "./StatusBadge";

export function RoomList({ recorders }: { recorders: Recorder[] }) {
  const { t, i18n } = useTranslation();
  return (
    <ul className="divide-y divide-slate-200 dark:divide-slate-800">
      {recorders.map((r) => (
        <li key={r.id}>
          <Link
            to={`/raum/${r.id}`}
            className="flex items-center gap-3 px-1 py-3 hover:bg-slate-50 dark:hover:bg-slate-900"
          >
            <span className="shrink-0">
              <StatusBadge state={r.status.state} />
            </span>
            <span className="min-w-0 flex-1 truncate text-lg font-bold">{r.room_name}</span>
            {keepsPlayer(r) && r.status.live_since ? (
              <span className="shrink-0 text-base font-bold tabular-nums">
                {t("since")} {formatClock(r.status.live_since, i18n.language)}
              </span>
            ) : null}
          </Link>
        </li>
      ))}
    </ul>
  );
}
