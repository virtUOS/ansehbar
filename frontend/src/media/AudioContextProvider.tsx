// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** One shared audio engine for the whole app (survives route changes). */
import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { AudioEngine } from "./audio";

export interface AudioApi {
  unlocked: boolean;
  unlock(): Promise<void>;
  audibleId: number | null;
  setAudible(id: number | null): void;
  attach(id: number, el: HTMLVideoElement): (() => void) | null;
  analyser(id: number): AnalyserNode | null;
  /** True only when the element can never have an analyser (native HLS). */
  analyserUnavailable(id: number): boolean;
}

const AudioCtx = createContext<AudioApi | undefined>(undefined);

export function AudioContextProvider({ children }: { children: ReactNode }) {
  const [engine] = useState(() => new AudioEngine());
  // Re-render whenever chains change or the context state changes.
  const version = useSyncExternalStore(engine.subscribe, engine.getVersion);
  // "unlocked" means: the context is running right now.
  const unlocked = engine.isRunning();
  const [audibleId, setAudibleId] = useState<number | null>(null);

  const unlock = useCallback(async () => {
    await engine.unlock();
  }, [engine]);
  const setAudible = useCallback((id: number | null) => {
    engine.setAudible(id);
    setAudibleId(id);
  }, [engine]);
  const attach = useCallback(
    (id: number, el: HTMLVideoElement) => engine.attach(id, el),
    [engine],
  );
  const analyser = useCallback((id: number) => engine.analyser(id), [engine]);
  const analyserUnavailable = useCallback((id: number) => engine.analyserUnavailable(id), [engine]);

  const value = useMemo<AudioApi>(
    () => ({ unlocked, unlock, audibleId, setAudible, attach, analyser, analyserUnavailable }),
    // version: chains/context state changed, consumers must re-resolve.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [unlocked, version, unlock, audibleId, setAudible, attach, analyser, analyserUnavailable],
  );
  return <AudioCtx.Provider value={value}>{children}</AudioCtx.Provider>;
}

export function useAudio(): AudioApi {
  const v = useContext(AudioCtx);
  if (!v) throw new Error("useAudio must be used inside AudioContextProvider");
  return v;
}
