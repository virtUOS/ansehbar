// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RotateCw } from "lucide-react";
import type { PlaybackState } from "../media/audio";

/** Playback state of one player plus a "reload" that remounts it (bump
 *  `reloadKey` in the player's key). Resets whenever `resetOn` changes. */
export function usePlayback(resetOn: unknown) {
  const [state, setState] = useState<PlaybackState | undefined>(undefined);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    setState(undefined);
  }, [resetOn]);
  const reload = useCallback(() => {
    setState(undefined);
    setReloadKey((k) => k + 1);
  }, []);
  return { state, onState: setState, reloadKey, reload };
}

/** Shown over the video area when the browser player has trouble. Sits at the
 *  bottom so the status badge (top left) stays visible. */
export function PlaybackOverlay({ state, onReload }: { state: PlaybackState | undefined; onReload: () => void }) {
  const { t } = useTranslation();
  if (state !== "waiting" && state !== "retrying" && state !== "failed") return null;
  return (
    <div className="pointer-events-none absolute inset-x-2 bottom-2 flex justify-center">
      <div
        role="status"
        className="pointer-events-auto flex flex-wrap items-center justify-center gap-2 rounded-lg bg-white/95 px-3 py-1.5 text-center text-sm font-semibold text-slate-900 dark:bg-slate-900/95 dark:text-slate-100"
      >
        <span aria-hidden>⚠</span>
        {state === "failed" ? (
          <>
            <span>{t("Playback failed")}</span>
            <button
              type="button"
              onClick={onReload}
              className="inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-3 py-1 text-white hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200"
            >
              <RotateCw aria-hidden className="h-4 w-4" />
              {t("Reload")}
            </button>
          </>
        ) : (
          <span>{t("Playback disrupted – retrying …")}</span>
        )}
      </div>
    </div>
  );
}
