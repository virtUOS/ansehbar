// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { memo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { TicketPlus, Volume2, VolumeX } from "lucide-react";
import type { Recorder } from "../api";
import { displayName, formatClock, presentation, recordingScheduled } from "../recorders";
import { RoomName } from "./RoomName";
import { LastRecordingWarning } from "./LastRecordingWarning";
import { HlsPlayer } from "../media/HlsPlayer";
import { LevelMeter } from "../media/LevelMeter";
import { useAudio } from "../media/AudioContextProvider";
import { OpencastIcon } from "./OpencastIcon";
import { StatusBadge } from "./StatusBadge";
import { StreamPlaceholder } from "./StreamPlaceholder";
import { captureFrame } from "../media/snapshot";
import { PlaybackOverlay, usePlayback } from "./PlaybackOverlay";

function RecorderTileInner({
  recorder,
  opencast = false,
  opencastStale = false,
  ticketsEnabled = false,
  onCreateTicket,
}: {
  recorder: Recorder;
  opencast?: boolean;
  opencastStale?: boolean;
  ticketsEnabled?: boolean;
  /** Must be stable: the tile is memoised. The dialog lives in the parent. */
  onCreateTicket?: (recorder: Recorder, screenshot: Blob | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const { unlocked, unlock, audibleId, setAudible } = useAudio();
  const shown = presentation(recorder);
  // Unknown but last seen live: keep the player (and its controls) on.
  const live = shown === "live" || shown === "live-unknown" || shown === "silent";
  const missing = shown === "missing";
  const silent = shown === "silent";
  const event = recorder.current_event;
  const audible = audibleId === recorder.id;
  const playback = usePlayback(live);
  const articleRef = useRef<HTMLElement>(null);

  const openTicket = async () => {
    // Capture first (inside the click), then open the dialog.
    const screenshot = await captureFrame(articleRef.current?.querySelector("video") ?? null);
    onCreateTicket?.(recorder, screenshot);
  };

  const toggleSound = async () => {
    if (audible) return setAudible(null);
    // The unlock must happen inside the click (autoplay policy).
    if (!unlocked) {
      try {
        await unlock();
      } catch {
        return;
      }
    }
    setAudible(recorder.id);
  };

  return (
    <article
      ref={articleRef}
      className={`overflow-hidden rounded-2xl border bg-white dark:bg-slate-900 ${
        missing
          ? "border-2 border-red-700"
          : "border-slate-200 dark:border-slate-800"
      }`}
    >
      <div className="relative aspect-video bg-slate-900">
        {live ? (
          <div className="absolute inset-0 flex">
            <div className="relative h-full min-w-0 flex-1">
              <HlsPlayer
                key={playback.reloadKey}
                id={recorder.id}
                label={displayName(recorder)}
                src={recorder.playback_url}
                onPlaybackState={playback.onState}
                className="h-full w-full bg-black object-contain"
              />
              <PlaybackOverlay
                state={playback.state}
                onReload={playback.reload}
              />
            </div>
            <div className="flex shrink-0 items-stretch bg-white/90 p-1.5 dark:bg-slate-900/90">
              <LevelMeter id={recorder.id} serverLevelDb={recorder.audio_level_db} />
            </div>
          </div>
        ) : (
          <StreamPlaceholder
            kind={shown}
            missingSince={recorder.missing_since}
            scheduled={recordingScheduled(recorder, opencast, opencastStale)}
          />
        )}
        <div className="absolute left-2 top-2 z-10 flex items-center gap-1.5">
          <StatusBadge
            state={
              shown === "inactive" || missing || silent
                ? shown
                : recorder.status.state
            }
          />
          {silent && recorder.silent_since ? (
            <span className="whitespace-nowrap rounded-full bg-white/90 px-2 py-0.5 text-xs font-bold tabular-nums text-slate-900 dark:bg-slate-900/90 dark:text-slate-100">
              {t("since {{time}}", {
                time: formatClock(recorder.silent_since, i18n.language),
              })}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex items-start gap-3 p-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-xl font-bold">
            <Link to={`/raum/${recorder.id}`} className="hover:underline">
              <RoomName recorder={recorder} />
            </Link>
          </h2>
          <LastRecordingWarning recorder={recorder} compact />
          {missing && (event || recorder.missing_since) ? (
            <p className="text-2xl font-extrabold tabular-nums">
              {t("from")}{" "}
              {formatClock(
                event ? event.start : recorder.missing_since!,
                i18n.language,
              )}
              {event ? (
                <span className="ml-2 text-sm font-semibold">
                  {t("until {{time}}", {
                    time: formatClock(event.end, i18n.language),
                  })}
                </span>
              ) : null}
            </p>
          ) : live && recorder.status.live_since ? (
            <p className="text-2xl font-extrabold tabular-nums">
              {t("since")}{" "}
              {formatClock(recorder.status.live_since, i18n.language)}
              {event ? (
                <span className="ml-2 text-sm font-semibold">
                  {t("until {{time}}", {
                    time: formatClock(event.end, i18n.language),
                  })}
                </span>
              ) : null}
            </p>
          ) : null}
          {(missing || live) && event ? (
            <p className="truncate text-sm font-semibold">{event.title}</p>
          ) : null}
          {!live && !missing && recorder.next_event ? (
            <p className="text-sm font-semibold tabular-nums">
              {t("next: {{time}}", {
                time: formatClock(recorder.next_event.start, i18n.language),
              })}
            </p>
          ) : null}
          <p className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
            {recorder.agent_id ? <OpencastIcon /> : null}
            <span className="truncate">{recorder.stream_name}</span>
          </p>
        </div>
        {ticketsEnabled && onCreateTicket ? (
          <button
            type="button"
            aria-label={t("Create ticket for {{room}}", { room: displayName(recorder) })}
            title={t("Create ticket for {{room}}", { room: displayName(recorder) })}
            onClick={() => void openTicket()}
            className="inline-flex items-center rounded-full bg-slate-100 p-2.5 text-slate-700 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            <TicketPlus aria-hidden className="h-5 w-5" />
          </button>
        ) : null}
        {live ? (
          <button
            type="button"
            aria-pressed={audible}
            aria-label={t("Sound for {{room}}", {
              room: displayName(recorder),
            })}
            onClick={() => void toggleSound()}
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-2.5 text-sm font-semibold transition-colors ${
              audible
                ? "bg-brand-400 text-slate-900 hover:bg-brand-500"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            }`}
          >
            {audible ? (
              <Volume2 aria-hidden className="h-5 w-5" />
            ) : (
              <VolumeX aria-hidden className="h-5 w-5" />
            )}
            {t("Sound")}
          </button>
        ) : null}
      </div>
    </article>
  );
}

/** Memoised: a poll that changes one recorder re-renders only that tile. */
export const RecorderTile = memo(RecorderTileInner);
