// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useRecorders } from "../useRecorders";
import { filterOverview, formatClock, sortForOverview } from "../recorders";
import { RecorderTile } from "../components/RecorderTile";
import { RoomList } from "../components/RoomList";
import { AudioUnlockButton } from "../media/AudioUnlockButton";

/** JS media query (not CSS hidden): hidden tiles would still mount players. */
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
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
  const { recorders, error, loading, lastUpdated } = useRecorders();
  const [mode, setMode] = useState<"now" | "all">("now");
  const [query, setQuery] = useState("");
  const wide = useMediaQuery("(min-width: 768px)");

  const sorted = useMemo(() => sortForOverview(recorders.filter((r) => r.active)), [recorders]);
  const nowCount = useMemo(() => sorted.filter((r) => r.status.state === "live").length, [sorted]);
  const shown = useMemo(() => filterOverview(sorted, mode, query), [sorted, mode, query]);
  const without = useMemo(
    () => (mode === "now" ? filterOverview(sorted, "all", query).filter((r) => r.status.state !== "live") : []),
    [sorted, mode, query],
  );

  const chip = (m: "now" | "all", label: string, n: number) => (
    <button
      type="button"
      aria-pressed={mode === m}
      onClick={() => setMode(m)}
      className={`rounded-full px-4 py-1.5 text-sm font-bold transition-colors ${
        mode === m
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
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {chip("now", "Now", nowCount)}
          {chip("all", "All rooms", sorted.length)}
        </div>
        <label className="relative min-w-0 flex-1 basis-48 sm:max-w-xs">
          <span className="sr-only">{t("Search room")}</span>
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Search room")}
            className="w-full rounded-full border border-slate-300 bg-white py-1.5 pl-9 pr-3 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
        </label>
        <div className="ml-auto">
          <AudioUnlockButton />
        </div>
      </div>

      {error ? (
        <p role="status" className="rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-950">
          {t("Status could not be updated – last update {{time}}", {
            time: lastUpdated ? formatClock(lastUpdated.toISOString(), i18n.language) : "–",
          })}
        </p>
      ) : null}

      {loading && recorders.length === 0 ? (
        <p className="text-slate-600 dark:text-slate-400">{t("Loading…")}</p>
      ) : shown.length === 0 ? (
        <p className="py-8 text-center text-lg text-slate-700 dark:text-slate-300">
          {mode === "now" && !query.trim() ? t("No recording room is streaming right now.") : t("No rooms found.")}
        </p>
      ) : wide ? (
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(22rem, 1fr))" }}>
          {shown.map((r) => (
            <RecorderTile key={r.id} recorder={r} />
          ))}
        </div>
      ) : (
        <RoomList recorders={shown} />
      )}

      {mode === "now" && without.length > 0 ? (
        <p className="text-sm text-slate-700 dark:text-slate-300">
          <span className="font-bold">{t("Currently without stream")}:</span>{" "}
          {without.map((r, i) => (
            <span key={r.id}>
              {i > 0 ? ", " : ""}
              <Link to={`/raum/${r.id}`} className="underline hover:text-brand-700 dark:hover:text-brand-300">
                {r.room_name}
              </Link>
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}
