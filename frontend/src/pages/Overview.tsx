// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useRecorders } from "../useRecorders";
import {
  displayName,
  emptyNowMessage,
  filterOverview,
  formatClock,
  keepsPlayer,
  newlyMissing,
  outsideNow,
  presentation,
  quietWithoutRecording,
  sortForOverview,
  type OverviewMode,
} from "../recorders";
import type { Recorder } from "../api";
import { RecorderTile } from "../components/RecorderTile";
import { RoomList } from "../components/RoomList";
import { RoomName } from "../components/RoomName";
import { UpcomingList } from "../components/UpcomingList";
import { MonitorBanner } from "../components/MonitorBanner";
import { AudioUnlockButton } from "../media/AudioUnlockButton";

/** JS media query (not CSS hidden): hidden tiles would still mount players. */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return matches;
}

export function Overview() {
  const { t, i18n } = useTranslation();
  const {
    recorders,
    error,
    loading,
    lastUpdated,
    monitorStale,
    monitorLastCheck,
    opencastEnabled,
    opencastStale,
    opencastLastSuccess,
  } = useRecorders();
  const [mode, setMode] = useState<OverviewMode>("now");
  const [query, setQuery] = useState("");
  const wide = useMediaQuery("(min-width: 768px)");

  const sorted = useMemo(
    () => sortForOverview(recorders.filter((r) => r.active)),
    [recorders],
  );
  const nowCount = useMemo(
    () =>
      sorted.filter((r) => keepsPlayer(r) || presentation(r) === "missing")
        .length,
    [sorted],
  );
  const todayCount = useMemo(
    () => filterOverview(sorted, "today", "").length,
    [sorted],
  );
  // Without Opencast there is no "Today" mode.
  const effMode: OverviewMode =
    !opencastEnabled && mode === "today" ? "now" : mode;
  const shown = useMemo(
    () => filterOverview(sorted, effMode, query),
    [sorted, effMode, query],
  );
  // Outside the tiles: definite "no stream" (without Opencast), "no recording
  // today" (with Opencast) and "status unknown" are listed apart.
  const outside = useMemo(() => {
    if (effMode === "all") return { offline: [], unknown: [], quiet: [] };
    const filtered = filterOverview(sorted, "all", query);
    const { offline, unknown } = outsideNow(filtered);
    const tiles = new Set(shown.map((r) => r.id));
    return {
      offline: opencastEnabled ? [] : offline,
      unknown: unknown.filter((r) => !tiles.has(r.id)),
      quiet: opencastEnabled
        ? filterOverview(quietWithoutRecording(sorted), "all", query)
        : [],
    };
  }, [sorted, shown, effMode, query, opencastEnabled]);
  const upcoming = useMemo(
    () =>
      opencastEnabled && effMode === "now"
        ? filterOverview(sorted, "all", query).filter((r) => r.next_event)
        : [],
    [sorted, effMode, query, opencastEnabled],
  );

  // Announce recorders that newly turn "missing"; never on the first load.
  const prevMissing = useRef<Set<number> | null>(null);
  const [announcement, setAnnouncement] = useState("");
  useEffect(() => {
    if (!lastUpdated) return;
    const fresh = newlyMissing(prevMissing.current, sorted);
    prevMissing.current = new Set(
      sorted.filter((r) => presentation(r) === "missing").map((r) => r.id),
    );
    if (fresh.length === 0) return;
    setAnnouncement(
      fresh
        .map((r) => t("Stream missing in {{room}}", { room: displayName(r) }))
        .join(". "),
    );
    const timer = setTimeout(() => setAnnouncement(""), 10000);
    return () => clearTimeout(timer);
  }, [sorted, lastUpdated, t]);

  const chip = (m: OverviewMode, label: string, n: number) => (
    <button
      type="button"
      aria-pressed={effMode === m}
      onClick={() => setMode(m)}
      className={`rounded-full px-4 py-1.5 text-sm font-bold transition-colors ${
        effMode === m
          ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
          : "bg-slate-100 text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
      }`}
    >
      {t(label)} ({n})
    </button>
  );

  return (
    <div className="space-y-4 p-4">
      <h1 className="sr-only">{t("Overview")}</h1>
      <MonitorBanner
        stale={monitorStale}
        lastCheck={monitorLastCheck}
        opencastStale={opencastStale}
        opencastLastSuccess={opencastLastSuccess}
      />
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {chip("now", "Now", nowCount)}
          {opencastEnabled ? chip("today", "Today", todayCount) : null}
          {chip("all", "All rooms", sorted.length)}
        </div>
        <label className="relative min-w-0 flex-1 basis-48 sm:max-w-xs">
          <span className="sr-only">{t("Search room")}</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search room")}
            className="w-full rounded-full border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm placeholder:text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:placeholder:text-slate-300"
          />
        </label>
        {wide ? (
          <div className="ml-auto">
            <AudioUnlockButton />
          </div>
        ) : null}
      </div>

      {error ? (
        <p
          role="status"
          className="rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-950"
        >
          {t("Status could not be updated – last update {{time}}", {
            time: lastUpdated
              ? formatClock(lastUpdated.toISOString(), i18n.language)
              : "–",
          })}
        </p>
      ) : null}

      {loading && recorders.length === 0 ? (
        <p className="text-slate-600 dark:text-slate-300">{t("Loading…")}</p>
      ) : error && recorders.length === 0 ? (
        <p className="py-8 text-center text-lg text-slate-700 dark:text-slate-300">
          {t("Status not available yet")}
        </p>
      ) : shown.length === 0 ? (
        <p className="py-8 text-center text-lg text-slate-700 dark:text-slate-300">
          {effMode === "all" ||
          query.trim() ||
          (opencastEnabled && effMode === "today")
            ? t("No rooms found.")
            : emptyNowMessage(sorted) === "unclear"
              ? t("Status currently unclear")
              : t("No recording room is streaming right now.")}
        </p>
      ) : wide ? (
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(22rem, 1fr))",
          }}
        >
          {shown.map((r) => (
            <RecorderTile key={r.id} recorder={r} opencast={opencastEnabled} />
          ))}
        </div>
      ) : (
        <RoomList recorders={shown} />
      )}

      {effMode !== "all" ? (
        <>
          <UpcomingList recorders={upcoming} />
          <RoomLinks
            label={t("Currently without stream")}
            recorders={outside.offline}
          />
          <RoomLinks
            label={t("No recording today")}
            recorders={outside.quiet}
          />
          <RoomLinks label={t("Status unknown")} recorders={outside.unknown} />
        </>
      ) : null}
    </div>
  );
}

function RoomLinks({
  label,
  recorders,
}: {
  label: string;
  recorders: Recorder[];
}) {
  if (recorders.length === 0) return null;
  return (
    <p className="text-sm text-slate-700 dark:text-slate-300">
      <span className="font-bold">{label}:</span>{" "}
      {recorders.map((r, i) => (
        <span key={r.id}>
          {i > 0 ? ", " : ""}
          <Link
            to={`/raum/${r.id}`}
            className="underline hover:text-brand-700 dark:hover:text-brand-300"
          >
            <RoomName recorder={r} />
          </Link>
        </span>
      ))}
    </p>
  );
}
