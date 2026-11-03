// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import type { Recorder } from "../api";
import { useTranslation } from "react-i18next";
import { hasLastRecordingProblems } from "../recorders";
import { RoomName } from "./RoomName";
import { OpencastIcon } from "./OpencastIcon";

/** A headed row of room links (quiet or unknown rooms) instead of running text. */
export function RoomPills({
  title,
  icon: Icon,
  recorders,
}: {
  title: string;
  icon: LucideIcon;
  recorders: Recorder[];
}) {
  const { t } = useTranslation();
  if (recorders.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-bold">{title}</h2>
      <ul className="flex flex-wrap gap-2">
        {recorders.map((r) => (
          <li key={r.id}>
            <Link
              to={`/raum/${r.id}`}
              className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800"
            >
              <Icon aria-hidden className="h-4 w-4 shrink-0" />
              <span>
                <RoomName recorder={r} />
              </span>
              {hasLastRecordingProblems(r) ? (
                <span className="text-amber-900 dark:text-amber-200">
                  <span aria-hidden>⚠</span>
                  <span className="sr-only">{t("Last recording had problems")}</span>
                </span>
              ) : null}
              {r.agent_id ? <OpencastIcon /> : null}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
