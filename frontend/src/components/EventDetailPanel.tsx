// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useTranslation } from "react-i18next";
import { EventTimeline } from "./EventTimeline";
import { LevelCurve } from "./LevelCurve";
import { useEventDetail } from "../useEventDetail";
import { useNow } from "../useNow";
import { timelineEntries } from "../timeline";

/** Timeline and level curve of one event, reloaded every 30 s. A leaf of its
 *  own, so its polling and clock never re-render the surrounding page.
 *  `liveSince`: the stream's live start, only while the event runs and the
 *  room is live; otherwise null. */
export function EventDetailPanel({ eventId, liveSince }: { eventId: number; liveSince: string | null }) {
  const { t } = useTranslation();
  const { detail, error } = useEventDetail(eventId);
  const now = useNow(30000);
  return (
    <>
      {error ? (
        <p role="status" className="text-sm text-slate-700 dark:text-slate-300">
          {t("Timeline could not be loaded")}
        </p>
      ) : null}
      {detail ? (
        <>
          <EventTimeline entries={timelineEntries(detail, now, liveSince)} />
          <LevelCurve detail={detail} />
        </>
      ) : !error ? (
        <p className="text-sm text-slate-700 dark:text-slate-300">{t("Loading…")}</p>
      ) : null}
    </>
  );
}
