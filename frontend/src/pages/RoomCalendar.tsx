// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import { ApiError, api, type CalendarEvent, type CalendarResponse, type Recorder } from "../api";
import { addDays, eventMarkers, groupByDay, isoDay, parseIsoDay, weekStart, type Marker } from "../calendar";
import { displayName, formatClock } from "../recorders";
import { problemText } from "../problemTexts";
import { useRecorders } from "../useRecorders";
import { useNow } from "../useNow";
import { EventDetailPanel } from "../components/EventDetailPanel";

type View = "woche" | "tag";

const control =
  "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-base font-medium transition-colors";
const idle = "bg-slate-100 text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700";
const pressed = "bg-slate-800 text-white dark:bg-slate-100 dark:text-slate-900";

/** Never the brand colour: amber/red for findings, neutral for "no findings". */
const MARKER_STYLE: Record<Marker["kind"], { symbol: string; cls: string }> = {
  missing: { symbol: "⚠", cls: "bg-red-100 text-red-950 ring-1 ring-red-700 dark:bg-red-950 dark:text-red-100" },
  silent: { symbol: "◐", cls: "bg-amber-100 text-amber-950 ring-1 ring-amber-700 dark:bg-amber-950 dark:text-amber-100" },
  alarm: { symbol: "🔔", cls: "bg-red-100 text-red-950 dark:bg-red-950 dark:text-red-100" },
  problem: { symbol: "⚠", cls: "bg-amber-100 text-amber-950 dark:bg-amber-950 dark:text-amber-100" },
  clean: { symbol: "✓", cls: "bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-100" },
};

function Markers({ markers, inline = false }: { markers: Marker[]; inline?: boolean }) {
  const { t, i18n } = useTranslation();
  const text = (m: Marker): string => {
    switch (m.kind) {
      case "missing":
        return t("Stream missing {{minutes}} min", { minutes: m.minutes });
      case "silent":
        return t("Silent {{minutes}} min", { minutes: m.minutes });
      case "alarm":
        return t("Alarm");
      case "problem":
        return m.problem ? problemText(t, m.problem, i18n.language) : "";
      case "clean":
        return t("No findings");
    }
  };
  // Inside a <button> only phrasing content is valid, so no list there.
  const Wrap = inline ? "span" : "ul";
  const Item = inline ? "span" : "li";
  const shown = markers.map((m) => ({ m, label: text(m) })).filter((x) => x.label !== "");
  if (shown.length === 0) return null;
  return (
    <Wrap className="flex flex-wrap gap-1">
      {shown.map(({ m, label }, i) => (
        <Item
          key={i}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${MARKER_STYLE[m.kind].cls}`}
        >
          <span aria-hidden>{MARKER_STYLE[m.kind].symbol}</span>
          {label}
        </Item>
      ))}
    </Wrap>
  );
}

function timeWindow(e: CalendarEvent, lang: string): string {
  return `${formatClock(e.start, lang)}–${formatClock(e.end, lang)}`;
}

export function RoomCalendar() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const params = useParams();
  const id = Number(params.id);
  const [search, setSearch] = useSearchParams();
  const view: View = search.get("ansicht") === "tag" ? "tag" : "woche";
  const date = parseIsoDay(search.get("datum")) ?? addDays(new Date(), 0);
  const from = view === "woche" ? weekStart(date) : date;
  const days = view === "woche" ? 7 : 1;
  const fromIso = isoDay(from);

  const { recorders } = useRecorders();
  const now = useNow(30000);
  const [state, setState] = useState<{
    key: string;
    data: CalendarResponse | null;
    error: string | null;
    notFound: boolean;
  }>({ key: "", data: null, error: null, notFound: false });
  const key = `${id}/${fromIso}/${days}`;

  useEffect(() => {
    let cancelled = false;
    setState({ key, data: null, error: null, notFound: false });
    if (!Number.isInteger(id)) {
      setState({ key, data: null, error: null, notFound: true });
      return;
    }
    api
      .calendar(id, fromIso, days)
      .then((data) => {
        if (!cancelled) setState({ key, data, error: null, notFound: false });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setState({ key, data: null, error: null, notFound: true });
        else setState({ key, data: null, error: e instanceof Error ? e.message : String(e), notFound: false });
      });
    return () => {
      cancelled = true;
    };
  }, [key, id, fromIso, days]);

  const current = state.key === key;
  const data = current ? state.data : null;
  const error = current ? state.error : null;
  const notFound = current && state.notFound;

  const go = (nextView: View, nextDate: Date) => setSearch({ ansicht: nextView, datum: isoDay(nextDate) });
  const recorderOf = (rid: number): Recorder | undefined => recorders.find((r) => r.id === rid);
  const own = recorderOf(id);
  const fromResponse = data?.recorders.find((r) => r.id === id);
  const room = own
    ? displayName(own)
    : fromResponse
      ? fromResponse.room_name.trim() || fromResponse.stream_name
      : "";
  const streamOf = (rid: number) => data?.recorders.find((r) => r.id === rid)?.stream_name ?? "";
  const multiple = (data?.recorders.length ?? 0) > 1;
  const today = isoDay(new Date());

  const dayLabel = (d: Date, weekday: "long" | "short") =>
    d.toLocaleDateString(lang, { weekday, day: "numeric", month: "numeric", year: "numeric" });
  const rangeLabel =
    view === "woche"
      ? `${from.toLocaleDateString(lang, { day: "numeric", month: "numeric" })}–${addDays(from, 6).toLocaleDateString(lang, { day: "numeric", month: "numeric", year: "numeric" })}`
      : dayLabel(from, "long");

  if (notFound) {
    return (
      <div className="mx-auto w-full max-w-4xl space-y-3">
        <h1 className="text-2xl font-bold">{t("Room not found")}</h1>
        <Link to="/" className="inline-flex min-h-11 items-center gap-2 underline">
          <ArrowLeft aria-hidden className="h-5 w-5" />
          {t("Back to overview")}
        </Link>
      </div>
    );
  }

  const streamName = (e: CalendarEvent) =>
    multiple ? <span className="block break-all font-mono text-xs text-slate-600 dark:text-slate-300">{streamOf(e.recorder_id)}</span> : null;

  return (
    <div className="mx-auto w-full min-w-0 max-w-6xl space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Link to={`/raum/${id}`} className="inline-flex min-h-11 items-center gap-1.5 pr-2 font-medium hover:underline">
          <ArrowLeft aria-hidden className="h-5 w-5" />
          {t("Back")}
        </Link>
        <h1 className="min-w-0 flex-1 basis-56 break-words text-2xl font-bold">{room ? t("Calendar – {{room}}", { room }) : t("Calendar")}</h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          <button
            type="button"
            aria-pressed={view === "woche"}
            onClick={() => go("woche", date)}
            className={`${control} ${view === "woche" ? pressed : idle}`}
          >
            {t("Week")}
          </button>
          <button
            type="button"
            aria-pressed={view === "tag"}
            onClick={() => go("tag", date)}
            className={`${control} ${view === "tag" ? pressed : idle}`}
          >
            {t("Day")}
          </button>
        </div>
        <div className="flex gap-1">
          <button type="button" onClick={() => go(view, addDays(date, -days))} className={`${control} ${idle}`}>
            <ChevronLeft aria-hidden className="h-5 w-5" />
            {t("Previous")}
          </button>
          <button type="button" onClick={() => go(view, new Date())} className={`${control} ${idle}`}>
            {t("Today")}
          </button>
          <button type="button" onClick={() => go(view, addDays(date, days))} className={`${control} ${idle}`}>
            {t("Next")}
            <ChevronRight aria-hidden className="h-5 w-5" />
          </button>
        </div>
        <p aria-live="polite" className="text-base font-semibold tabular-nums">
          {rangeLabel}
        </p>
      </div>

      {error ? (
        <p role="alert" className="rounded-lg bg-red-100 px-3 py-2 text-sm text-red-900 dark:bg-red-950 dark:text-red-100">
          ⚠ {t("Calendar could not be loaded")}: {error}
        </p>
      ) : null}
      {!data && !error ? <p role="status">{t("Loading…")}</p> : null}

      {data && view === "woche" ? (
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-7">
          {groupByDay(data.events, from, 7).map(({ day, events }) => {
            const d = parseIsoDay(day)!;
            const isToday = day === today;
            return (
              <section
                key={day}
                aria-labelledby={`day-${day}`}
                className={`min-w-0 space-y-2 rounded-xl p-2 ${isToday ? "bg-slate-100 ring-2 ring-slate-800 dark:bg-slate-800 dark:ring-slate-100" : "bg-slate-50 dark:bg-slate-900"}`}
              >
                <h2 id={`day-${day}`} className="text-sm font-bold">
                  {d.toLocaleDateString(lang, { weekday: "short" })}{" "}
                  <span className="tabular-nums">{d.toLocaleDateString(lang, { day: "numeric", month: "numeric" })}</span>
                  {isToday ? (
                    <span className="ml-1.5 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-white dark:bg-slate-100 dark:text-slate-900">
                      {t("Today")}
                    </span>
                  ) : null}
                </h2>
                {events.length === 0 ? (
                  <p className="text-sm text-slate-600 dark:text-slate-300">{t("No events")}</p>
                ) : (
                  <ul className="space-y-2">
                    {events.map((e) => (
                      <li key={e.id}>
                        <button
                          type="button"
                          onClick={() => go("tag", d)}
                          className="block min-h-11 w-full space-y-1 rounded-lg border border-slate-300 bg-white p-2 text-left hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-950 dark:hover:bg-slate-800"
                        >
                          <span className="block text-xs font-semibold tabular-nums">{timeWindow(e, lang)}</span>
                          <span className="block break-words text-sm font-semibold">{e.title}</span>
                          {streamName(e)}
                          <Markers markers={eventMarkers(e, now)} inline />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      ) : null}

      {data && view === "tag" ? (
        (() => {
          const [{ events }] = groupByDay(data.events, from, 1);
          if (events.length === 0) return <p className="text-slate-700 dark:text-slate-300">{t("No events")}</p>;
          return (
            <div className="space-y-4">
              {events.map((e) => {
                const rec = recorderOf(e.recorder_id);
                const running = Date.parse(e.start) <= now.getTime() && now.getTime() < Date.parse(e.end);
                const liveSince = rec && rec.status.state === "live" && running ? rec.status.live_since : null;
                return (
                  <section
                    key={e.id}
                    aria-labelledby={`event-${e.id}`}
                    className="space-y-2 rounded-xl border border-slate-300 p-3 dark:border-slate-700"
                  >
                    <h2 id={`event-${e.id}`} className="break-words text-lg font-semibold">
                      <span className="tabular-nums">{timeWindow(e, lang)}</span> {e.title}
                    </h2>
                    {streamName(e)}
                    <Markers markers={eventMarkers(e, now)} />
                    <EventDetailPanel eventId={e.id} liveSince={liveSince} eventEnd={e.end} />
                  </section>
                );
              })}
            </div>
          );
        })()
      ) : null}
    </div>
  );
}
