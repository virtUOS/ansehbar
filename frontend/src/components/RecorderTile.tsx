// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Volume2, VolumeX } from "lucide-react";
import type { Recorder } from "../api";
import { formatClock } from "../recorders";
import { HlsPlayer } from "../media/HlsPlayer";
import { LevelMeter } from "../media/LevelMeter";
import { useAudio } from "../media/AudioContextProvider";
import { StatusBadge } from "./StatusBadge";

function RecorderTileInner({ recorder }: { recorder: Recorder }) {
  const { t, i18n } = useTranslation();
  const { unlocked, unlock, audibleId, setAudible } = useAudio();
  const live = recorder.status.state === "live";
  const audible = audibleId === recorder.id;

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
    <article className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="relative aspect-video bg-slate-900">
        {live ? (
          <div className="absolute inset-0 flex">
            <HlsPlayer
              id={recorder.id}
              src={recorder.playback_url}
              className="h-full min-w-0 flex-1 bg-black object-contain"
            />
            <div className="flex shrink-0 items-stretch bg-white/90 p-1.5 dark:bg-slate-900/90">
              <LevelMeter id={recorder.id} />
            </div>
          </div>
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm font-medium text-slate-800 dark:text-slate-100"
            style={{
              backgroundImage:
                "repeating-linear-gradient(135deg, rgb(148 163 184 / 0.35) 0 10px, rgb(148 163 184 / 0.15) 10px 20px)",
            }}
          >
            <span className="rounded bg-white/80 px-2 py-1 dark:bg-slate-900/80">
              {t("No stream – the recorder is not sending right now")}
            </span>
          </div>
        )}
        <div className="absolute left-2 top-2">
          <StatusBadge state={recorder.status.state} />
        </div>
      </div>
      <div className="flex items-start gap-3 p-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-xl font-bold">
            <Link to={`/raum/${recorder.id}`} className="hover:underline">
              {recorder.room_name}
            </Link>
          </h2>
          {live && recorder.status.live_since ? (
            <p className="text-2xl font-extrabold tabular-nums">
              {t("since")} {formatClock(recorder.status.live_since, i18n.language)}
            </p>
          ) : null}
          <p className="truncate text-xs text-slate-600 dark:text-slate-400">{recorder.stream_name}</p>
        </div>
        {live ? (
          <button
            type="button"
            aria-pressed={audible}
            aria-label={t(audible ? "Turn off sound for {{room}}" : "Turn on sound for {{room}}", {
              room: recorder.room_name,
            })}
            onClick={() => void toggleSound()}
            className={`rounded-full p-2.5 transition-colors ${
              audible
                ? "bg-brand-400 text-slate-900 hover:bg-brand-500"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
            }`}
          >
            {audible ? <Volume2 aria-hidden className="h-5 w-5" /> : <VolumeX aria-hidden className="h-5 w-5" />}
          </button>
        ) : null}
      </div>
    </article>
  );
}

/** Memoised: a poll that changes one recorder re-renders only that tile. */
export const RecorderTile = memo(RecorderTileInner);
