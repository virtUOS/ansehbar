// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** One shared audio engine for the whole app (survives route changes). */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AudioEngine } from "./audio";

export interface AudioApi {
  unlocked: boolean;
  unlock(): Promise<void>;
  audibleId: number | null;
  setAudible(id: number | null): void;
  attach(id: number, el: HTMLVideoElement): (() => void) | null;
  analyser(id: number): AnalyserNode | null;
}

const AudioCtx = createContext<AudioApi | undefined>(undefined);

export function AudioContextProvider({ children }: { children: ReactNode }) {
  const engine = useRef<AudioEngine | null>(null);
  engine.current ??= new AudioEngine();
  const [unlocked, setUnlocked] = useState(false);
  const [audibleId, setAudibleId] = useState<number | null>(null);

  const unlock = useCallback(async () => {
    await engine.current!.unlock();
    setUnlocked(true);
  }, []);
  const setAudible = useCallback((id: number | null) => {
    engine.current!.setAudible(id);
    setAudibleId(id);
  }, []);
  const attach = useCallback(
    (id: number, el: HTMLVideoElement) => engine.current!.attach(id, el),
    [],
  );
  const analyser = useCallback((id: number) => engine.current!.analyser(id), []);

  const value = useMemo<AudioApi>(
    () => ({ unlocked, unlock, audibleId, setAudible, attach, analyser }),
    [unlocked, unlock, audibleId, setAudible, attach, analyser],
  );
  return <AudioCtx.Provider value={value}>{children}</AudioCtx.Provider>;
}

export function useAudio(): AudioApi {
  const v = useContext(AudioCtx);
  if (!v) throw new Error("useAudio must be used inside AudioContextProvider");
  return v;
}
