// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef } from "react";
import Hls from "hls.js";
import { markNative, type PlaybackState } from "./audio";
import { useAudio } from "./AudioContextProvider";

const RETRY_DELAY_MS = 10_000;
const MAX_RETRIES = 30;

interface Props {
  id: number;
  src: string;
  className?: string;
  /** Accessible name of the video (the room name). */
  label?: string;
  onError?: (message: string) => void;
  /** playing | waiting (stalled after it played) | retrying | failed (gave up). */
  onPlaybackState?: (state: PlaybackState) => void;
}

export function HlsPlayer({ id, src, className, label, onError, onPlaybackState }: Props) {
  const ref = useRef<HTMLVideoElement>(null);
  const { attach, markForceMuted, audibleId, setAudible, setPlaybackState } = useAudio();
  const audibleRef = useRef(audibleId);
  audibleRef.current = audibleId;
  const setAudibleRef = useRef(setAudible);
  setAudibleRef.current = setAudible;
  // Keep the latest callback without restarting playback when it changes.
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const onStateRef = useRef(onPlaybackState);
  onStateRef.current = onPlaybackState;

  const useHlsJs = Hls.isSupported();

  // Audio routing (separate from playback so a src change does not re-route).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!useHlsJs) markNative(el);
    const detach = attach(id, el);
    return () => {
      detach?.();
      // A vanished tile must not leave its room audible for later.
      if (audibleRef.current === id) setAudibleRef.current(null);
    };
  }, [id, attach, useHlsJs]);

  // Playback; depends on src only.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    let hls: Hls | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;
    let hasPlayed = false;
    let current: PlaybackState | null = null;

    // Playback state goes to the engine (level meter) and to the caller (overlay).
    const setState = (state: PlaybackState) => {
      if (cancelled || state === current) return;
      current = state;
      setPlaybackState(id, state);
      onStateRef.current?.(state);
    };
    setPlaybackState(id, null); // new source: nothing known yet
    const onPlaying = () => {
      hasPlayed = true;
      setState("playing");
    };
    // Before the first frame "waiting" is just loading; failures to start
    // surface as errors (retrying/failed).
    const onWaiting = () => {
      if (hasPlayed) setState("waiting");
    };
    // "stalled" can fire while enough data is buffered (MSE): only count it
    // when playback really cannot continue.
    const onStalled = () => {
      if (hasPlayed && el.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) setState("waiting");
    };
    el.addEventListener("playing", onPlaying);
    el.addEventListener("waiting", onWaiting);
    el.addEventListener("stalled", onStalled);
    const removeListeners = () => {
      el.removeEventListener("playing", onPlaying);
      el.removeEventListener("waiting", onWaiting);
      el.removeEventListener("stalled", onStalled);
    };
    const resetRetries = () => {
      retries = 0;
    };
    /** Schedule another attempt, or give up after MAX_RETRIES. */
    const retry = (again: () => void) => {
      if (retries++ < MAX_RETRIES) {
        setState("retrying");
        timer = setTimeout(again, RETRY_DELAY_MS);
      } else {
        setState("failed");
      }
    };

    const report = (err: unknown) => {
      if (!cancelled) onErrorRef.current?.(err instanceof Error ? err.message : String(err));
    };
    // Muted playback beats a black tile: on an autoplay rejection fall back to
    // muted and retry.
    const play = () => {
      el.play().catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return; // src changed/torn down
        if (err instanceof DOMException && err.name === "NotAllowedError") {
          el.muted = true;
          markForceMuted(id, true);
          el.play().catch(report);
          return;
        }
        report(err);
      });
    };

    if (!useHlsJs) {
      if (!el.canPlayType("application/vnd.apple.mpegurl")) {
        onErrorRef.current?.("HLS is not supported by this browser");
        setState("failed");
        return () => {
          cancelled = true;
          removeListeners();
        };
      }
      const load = () => {
        if (cancelled) return;
        el.src = src;
        play();
      };
      const onNativeError = () => {
        if (cancelled) return;
        onErrorRef.current?.(`media error ${el.error?.code ?? "?"}`);
        retry(() => {
          el.removeAttribute("src");
          el.load();
          load();
        });
      };
      el.addEventListener("error", onNativeError);
      el.addEventListener("playing", resetRetries);
      load();
      return () => {
        cancelled = true;
        clearTimeout(timer);
        removeListeners();
        el.removeEventListener("error", onNativeError);
        el.removeEventListener("playing", resetRetries);
        el.removeAttribute("src");
        el.load();
      };
    }

    const start = () => {
      if (cancelled) return;
      hls = new Hls({ lowLatencyMode: false });
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        retries = 0;
        play();
      });
      hls.on(Hls.Events.ERROR, (_e, data) => {
        if (!data.fatal || cancelled) return;
        onErrorRef.current?.(`${data.type}: ${data.details}`);
        hls?.destroy();
        hls = null;
        retry(start);
      });
      hls.loadSource(src);
      hls.attachMedia(el);
    };
    start();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      removeListeners();
      hls?.destroy();
      hls?.detachMedia();
    };
  }, [src, useHlsJs, id, markForceMuted, setPlaybackState]);

  return <video ref={ref} aria-label={label} className={className} autoPlay playsInline muted />;
}
