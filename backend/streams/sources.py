# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Stream sources and live evaluation. Plain Python, no Django imports."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from urllib.parse import urljoin

import httpx

from streams.hls import parse_master, parse_media

# State values match recorders.models.RecorderStatus (deliberately not imported).
LIVE = "live"
OFFLINE = "offline"
UNKNOWN = "unknown"

DEFAULT_TARGET_DURATION = 6.0


@dataclass(frozen=True)
class Probe:
    reachable: bool  # False: network error, timeout or 5xx
    exists: bool  # False: 404/410
    media_sequence: int | None
    target_duration: float | None
    detail: str = ""


@dataclass(frozen=True)
class LiveState:
    state: str
    live_since: datetime | None
    media_sequence: int | None
    sequence_changed_at: datetime | None
    detail: str


class StreamSource(Protocol):
    def playback_url(self, stream_name: str) -> str: ...

    def probe(self, stream_name: str) -> Probe: ...


class HlsStreamSource:
    def __init__(self, url_template: str, client: httpx.Client, timeout: float = 5.0):
        self.url_template = url_template
        self.client = client
        self.timeout = timeout

    def playback_url(self, stream_name: str) -> str:
        # Stream names are case-sensitive; never normalize them.
        return self.url_template.replace("{stream}", stream_name)

    def _get(self, url: str) -> tuple[httpx.Response | None, Probe | None]:
        """Fetch url; return (response, None) on 200 or (None, final probe)."""
        try:
            response = self.client.get(url, timeout=self.timeout)
        except httpx.HTTPError as exc:
            return None, Probe(False, False, None, None, f"{type(exc).__name__}: {exc}")
        if response.status_code in (404, 410):
            return None, Probe(True, False, None, None, f"HTTP {response.status_code}")
        if response.status_code != 200:
            return None, Probe(
                False, False, None, None, f"HTTP {response.status_code}"
            )
        return response, None

    def probe(self, stream_name: str) -> Probe:
        master_url = self.playback_url(stream_name)
        response, failure = self._get(master_url)
        if failure:
            return failure
        variants = parse_master(response.text)
        if variants:
            response, failure = self._get(urljoin(master_url, variants[0]))
            if failure:
                return failure
        sequence, target = parse_media(response.text)
        return Probe(True, True, sequence, target)


def evaluate(
    prev: LiveState, probe: Probe, now: datetime, stale_factor: int
) -> LiveState:
    if not probe.reachable:
        return replace(prev, state=UNKNOWN, detail=probe.detail)
    if not probe.exists:
        return LiveState(OFFLINE, None, None, None, probe.detail)
    if probe.media_sequence is None:
        # Chunklist exists but cannot be judged as advancing: treat as offline.
        return LiveState(
            OFFLINE, None, None, None, "Chunklist without EXT-X-MEDIA-SEQUENCE"
        )

    if prev.media_sequence is None or probe.media_sequence != prev.media_sequence:
        changed_at = now
    else:
        changed_at = prev.sequence_changed_at or now

    target = probe.target_duration or DEFAULT_TARGET_DURATION
    age = (now - changed_at).total_seconds()
    if age <= stale_factor * target:
        live_since = prev.live_since or now  # offline always clears live_since
        return LiveState(LIVE, live_since, probe.media_sequence, changed_at, "")
    return LiveState(
        OFFLINE,
        None,
        probe.media_sequence,
        changed_at,
        f"Media sequence unchanged for {int(age)} s",
    )
