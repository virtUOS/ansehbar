// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Maximize, Volume2, VolumeX } from "lucide-react";
import { useRecorders } from "../useRecorders";
import { displayName, formatClock, formatDuration, presentation, recordingScheduled, scheduleUnclear, stateTransition } from "../recorders";
import { RoomName } from "../components/RoomName";
import { AgentStateText } from "../components/AgentStateText";
import { StatusBadge } from "../components/StatusBadge";
import { StreamPlaceholder } from "../components/StreamPlaceholder";
import { OpencastIcon } from "../components/OpencastIcon";
import { AudioUnlockButton } from "../media/AudioUnlockButton";
import { MonitorBanner } from "../components/MonitorBanner";
import { PlaybackOverlay, usePlayback } from "../components/PlaybackOverlay";
import { HlsPlayer } from "../media/HlsPlayer";
import { LevelMeter } from "../media/LevelMeter";
import { useAudio } from "../media/AudioContextProvider";

/** Ticks every second on its own, so the player never re-renders. */
function LiveBadge({ since }: { since: string | null }) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-700 px-3 py-1 text-sm font-bold text-white">
      <span aria-hidden>●</span>
      {t("LIVE")}
      {since ? <span className="tabular-nums">{formatDuration(since, now)}</span> : null}
    </span>
  );
}

type FsVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };

const btn =
  "inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl px-4 py-2 text-base font-semibold transition-colors";
const btnIdle = "bg-slate-100 text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700";

export function RoomView() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const params = useParams();
  const id = Number(params.id);
  const { recorders, error, loading, lastUpdated, monitorStale, monitorLastCheck, opencastEnabled: opencast, opencastStale, opencastLastSuccess, opencastErrorKind, opencastNotice, opencastRequested } = useRecorders();
  const { unlocked, unlock, audibleId, setAudible } = useAudio();
  const container = useRef<HTMLDivElement>(null);
  // Each announcement gets a new seq, so the live region node is recreated and
  // identical texts (flapping stream) are announced again.
  const [announcement, setAnnouncement] = useState({ text: "", seq: 0 });
  const announce = (text: string) => setAnnouncement((a) => ({ text, seq: a.seq + 1 }));

  const recorder = recorders.find((r) => r.id === id);
  const state = recorder?.status.state;
  const room = recorder ? displayName(recorder) : "";
  const prevState = useRef<typeof state>(undefined);
  const prevMissing = useRef<boolean | undefined>(undefined);
  const isMissing = recorder ? presentation(recorder) === "missing" : undefined;

  useEffect(() => {
    // Reset when the user switches rooms so no cross-room announcement fires.
    prevState.current = undefined;
    prevMissing.current = undefined;
    setAnnouncement((a) => ({ text: "", seq: a.seq + 1 }));
  }, [id]);

  useEffect(() => {
    if (isMissing === undefined) return;
    const before = prevMissing.current;
    prevMissing.current = isMissing;
    if (before === false && isMissing) setAnnouncement((a) => ({ text: t("Stream missing in {{room}}", { room }), seq: a.seq + 1 }));
  }, [isMissing, room, t]);

  useEffect(() => {
    if (!state) return;
    // "unknown" is ignored: live -> unknown -> live is not a new start.
    if (state === "unknown") return;
    const change = stateTransition(prevState.current, state);
    prevState.current = state;
    if (change === "started") announce(t("Stream in {{room}} started", { room }));
    else if (change === "ended") announce(t("Stream in {{room}} ended", { room }));
  }, [state, room, t]);

  const switchable = useMemo(
    () =>
      recorders
        .filter((r) => r.active)
        .sort((a, b) => displayName(a).localeCompare(displayName(b), "de", { numeric: true })),
    [recorders],
  );

  const shown = recorder ? presentation(recorder) : undefined;
  const event = recorder?.current_event ?? null;
  // Unknown but last seen live: keep the player (and its controls) on.
  const live = shown === "live" || shown === "live-unknown";
  const audible = audibleId === id;
  const playback = usePlayback(`${id}-${live}`);

  const toggleSound = async () => {
    if (audible) return setAudible(null);
    if (!unlocked) {
      try {
        await unlock();
      } catch {
        return;
      }
    }
    setAudible(id);
  };

  const findVideo = () => container.current?.querySelector("video") as FsVideo | null | undefined;
  const canFullscreen =
    typeof document !== "undefined" &&
    (!!document.documentElement.requestFullscreen || "webkitEnterFullscreen" in HTMLVideoElement.prototype);
  const goFullscreen = () => {
    const el = container.current;
    if (el?.requestFullscreen) {
      void el.requestFullscreen().catch(() => {
        try {
          findVideo()?.webkitEnterFullscreen?.();
        } catch {
          /* metadata not loaded yet */
        }
      });
    } else {
      try {
        findVideo()?.webkitEnterFullscreen?.();
      } catch {
        /* metadata not loaded yet */
      }
    }
  };

  const notice = (
    <>
      <MonitorBanner
        stale={monitorStale}
        lastCheck={monitorLastCheck}
        opencastStale={opencastStale}
        opencastLastSuccess={opencastLastSuccess}
        opencastNotice={opencastNotice}
        opencastRequested={opencastRequested}
      />
      {error ? (
        <p role="status" className="rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-950">
          {t("Status could not be updated – last update {{time}}", {
            time: lastUpdated ? formatClock(lastUpdated.toISOString(), i18n.language) : "–",
          })}
        </p>
      ) : null}
    </>
  );

  if (!recorder) {
    return (
      <div className="mx-auto w-full max-w-4xl space-y-3">
        {notice}
        {error && !lastUpdated ? (
          <p className="py-8 text-center text-lg text-slate-700 dark:text-slate-300">
            {t("Status not available yet")}
          </p>
        ) : loading || !lastUpdated ? (
          <p>{t("Loading…")}</p>
        ) : (
          <>
            <h1 className="text-2xl font-bold">{t("Room not found")}</h1>
            <Link to="/" className="mt-3 inline-flex min-h-11 items-center gap-2 underline">
              <ArrowLeft aria-hidden className="h-5 w-5" />
              {t("Back to overview")}
            </Link>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto w-full min-w-0 max-w-4xl space-y-3">
      {notice}
      <div aria-live="polite" className="sr-only">
        <span key={announcement.seq}>{announcement.text}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Link to="/" className="inline-flex min-h-11 items-center gap-1.5 pr-2 font-medium hover:underline">
          <ArrowLeft aria-hidden className="h-5 w-5" />
          {t("Back")}
        </Link>
        <h1 className="min-w-0 flex-1 basis-56 break-words text-2xl font-bold">
          <RoomName recorder={recorder} />
        </h1>
        <label className="flex items-center">
          <span className="sr-only">{t("Switch room")}</span>
          <select
            value={recorder.id}
            onChange={(e) => navigate(`/raum/${e.target.value}`)}
            className="min-h-11 max-w-full rounded-lg border border-slate-300 bg-white px-2 text-base dark:border-slate-700 dark:bg-slate-900"
          >
            {switchable.some((r) => r.id === recorder.id) ? null : (
              <option value={recorder.id}>{displayName(recorder)}</option>
            )}
            {switchable.map((r) => (
              <option key={r.id} value={r.id}>
                {displayName(r)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <AudioUnlockButton />

      <div ref={container} className="relative aspect-video overflow-hidden rounded-2xl bg-slate-900">
        {live ? (
          <div className="absolute inset-0 flex">
            <div className="relative h-full min-w-0 flex-1">
              <HlsPlayer
                key={`${recorder.id}-${playback.reloadKey}`}
                id={recorder.id}
                label={displayName(recorder)}
                src={recorder.playback_url}
                onPlaybackState={playback.onState}
                className="h-full w-full bg-black object-contain"
              />
              <PlaybackOverlay state={playback.state} onReload={playback.reload} />
            </div>
            <div className="flex shrink-0 items-stretch bg-white/90 p-1.5 dark:bg-slate-900/90">
              <LevelMeter key={recorder.id} id={recorder.id} />
            </div>
          </div>
        ) : !shown ? null : (
          <StreamPlaceholder
            kind={shown}
            missingSince={recorder.missing_since}
            scheduled={recordingScheduled(recorder, opencast, scheduleUnclear(opencastStale, opencastErrorKind))}
          >
            {recorder.status.checked_at && shown !== "inactive" ? (
              <span className="rounded bg-white/80 px-2 py-1 text-xs dark:bg-slate-900/80">
                {t("Last checked {{time}}", { time: formatClock(recorder.status.checked_at, i18n.language) })}
              </span>
            ) : null}
          </StreamPlaceholder>
        )}
        <div className="absolute left-2 top-2 z-10">
          {shown === "live" ? (
            <LiveBadge since={recorder.status.live_since} />
          ) : (
            <StatusBadge state={shown === "inactive" || shown === "missing" ? shown : recorder.status.state} />
          )}
        </div>
      </div>

      {event ? (
        <p className="text-lg font-semibold">
          <span className="tabular-nums">
            {formatClock(event.start, i18n.language)}–{formatClock(event.end, i18n.language)}
          </span>{" "}
          {event.title}
        </p>
      ) : recorder.next_event ? (
        <p className="text-base font-semibold">
          {t("Next today: {{time}} {{title}}", {
            time: formatClock(recorder.next_event.start, i18n.language),
            title: recorder.next_event.title,
          })}
        </p>
      ) : null}

      <p className="break-words text-sm text-slate-600 dark:text-slate-300">
        <span className="font-mono">{recorder.stream_name}</span>
        {!opencast ? null : recorder.agent_id ? (
          <>
            {" · "}
            <OpencastIcon className="mr-1" />
            {t("Opencast agent")}: <span className="font-mono">{recorder.agent_id}</span> · <AgentStateText state={recorder.status.agent_state} />
          </>
        ) : (
          <>
            {" · "}
            {t("Opencast agent")}: {t("Not linked")}
          </>
        )}
      </p>

      {live ? (
        <div className="flex gap-3">
          <button
            type="button"
            aria-pressed={audible}
            aria-label={t("Sound for {{room}}", { room: displayName(recorder) })}
            onClick={() => void toggleSound()}
            className={`${btn} ${audible ? "bg-brand-400 text-slate-900 hover:bg-brand-500" : btnIdle}`}
          >
            {audible ? <Volume2 aria-hidden className="h-5 w-5" /> : <VolumeX aria-hidden className="h-5 w-5" />}
            {t("Sound")}
          </button>
          {canFullscreen ? (
            <button type="button" onClick={goFullscreen} className={`${btn} ${btnIdle}`}>
              <Maximize aria-hidden className="h-5 w-5" />
              {t("Fullscreen")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
