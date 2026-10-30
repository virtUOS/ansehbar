// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Web Audio engine: one AudioContext per page, per element
 *  MediaElementSource -> Analyser -> Gain -> destination. Framework-free so it
 *  can be reasoned about (and reused) outside React. */

/** Elements played by native HLS (Safari/iOS). Their media may be tainted, so
 *  routing them through Web Audio could silence them: they are never routed;
 *  audibility is controlled via el.muted and no analyser is offered. */
const nativeElements = new WeakSet<HTMLMediaElement>();
export function markNative(el: HTMLMediaElement): void {
  nativeElements.add(el);
}

interface Chain {
  source: MediaElementAudioSourceNode;
  analyser: AnalyserNode;
  gain: GainNode;
}

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private elements = new Map<number, HTMLVideoElement>();
  private chains = new Map<number, Chain>();
  /** createMediaElementSource may only be called once per element. */
  private sources = new WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>();
  private audibleId: number | null = null;
  private unlocked = false;
  private unlocking: Promise<void> | null = null;

  isUnlocked(): boolean {
    return this.unlocked;
  }

  async unlock(): Promise<void> {
    if (this.unlocked) return;
    this.unlocking ??= (async () => {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) throw new Error("Web Audio is not supported");
      this.ctx ??= new Ctor();
      await this.ctx.resume();
      this.unlocked = true;
      for (const [id, el] of this.elements) this.wire(id, el);
      this.applyAudibility();
    })().finally(() => {
      this.unlocking = null;
    });
    return this.unlocking;
  }

  setAudible(id: number | null): void {
    this.audibleId = id;
    this.applyAudibility();
  }

  attach(id: number, el: HTMLVideoElement): () => void {
    this.elements.set(id, el);
    if (this.unlocked) {
      this.wire(id, el);
      this.applyAudibility();
    }
    return () => {
      // Ignore stale cleanups (id re-attached with another element).
      if (this.elements.get(id) !== el) return;
      this.elements.delete(id);
      this.unwire(id);
      el.muted = true;
    };
  }

  analyser(id: number): AnalyserNode | null {
    return this.chains.get(id)?.analyser ?? null;
  }

  private wire(id: number, el: HTMLVideoElement): void {
    if (!this.ctx || nativeElements.has(el) || this.chains.has(id)) return;
    let source = this.sources.get(el);
    if (!source) {
      source = this.ctx.createMediaElementSource(el);
      this.sources.set(el, source);
    }
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 2048;
    const gain = this.ctx.createGain();
    gain.gain.value = id === this.audibleId ? 1 : 0;
    source.connect(analyser);
    analyser.connect(gain);
    gain.connect(this.ctx.destination);
    this.chains.set(id, { source, analyser, gain });
    el.muted = false;
  }

  private unwire(id: number): void {
    const chain = this.chains.get(id);
    if (!chain) return;
    chain.source.disconnect();
    chain.analyser.disconnect();
    chain.gain.disconnect();
    this.chains.delete(id);
  }

  private applyAudibility(): void {
    if (!this.unlocked) return;
    for (const [id, el] of this.elements) {
      const audible = id === this.audibleId;
      const chain = this.chains.get(id);
      if (chain) chain.gain.gain.value = audible ? 1 : 0;
      else if (nativeElements.has(el)) el.muted = !audible;
    }
  }
}
