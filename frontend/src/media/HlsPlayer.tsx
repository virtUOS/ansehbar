// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef } from "react";
import Hls from "hls.js";
import { markNative } from "./audio";
import { useAudio } from "./AudioContextProvider";

const RETRY_DELAY_MS = 10_000;
const MAX_RETRIES = 30;

interface Props {
  id: number;
  src: string;
  className?: string;
  onError?: (message: string) => void;
}

export function HlsPlayer({ id, src, className, onError }: Props) {
  const ref = useRef<HTMLVideoElement>(null);
  const { attach } = useAudio();
  // Keep the latest callback without restarting playback when it changes.
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const useHlsJs = Hls.isSupported();

  // Audio routing (separate from playback so a src change does not re-route).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!useHlsJs) markNative(el);
    const detach = attach(id, el);
    return () => detach?.();
  }, [id, attach, useHlsJs]);

  // Playback; depends on src only.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    let hls: Hls | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;

    const play = () => void el.play().catch(() => {});

    if (!useHlsJs) {
      if (el.canPlayType("application/vnd.apple.mpegurl")) {
        el.src = src;
        play();
      } else {
        onErrorRef.current?.("HLS is not supported by this browser");
      }
      return () => {
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
        if (retries++ < MAX_RETRIES) timer = setTimeout(start, RETRY_DELAY_MS);
      });
      hls.loadSource(src);
      hls.attachMedia(el);
    };
    start();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      hls?.destroy();
      hls?.detachMedia();
    };
  }, [src, useHlsJs]);

  return <video ref={ref} className={className} autoPlay playsInline muted />;
}
