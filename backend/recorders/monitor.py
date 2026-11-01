# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""One monitoring cycle: probe active recorders, persist their status."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from recorders.models import MonitorSettings, Recorder, RecorderStatus
from streams.sources import LiveState, Probe, StreamSource, evaluate


def _to_live_state(status: RecorderStatus) -> LiveState:
    return LiveState(
        status.state,
        status.live_since,
        status.media_sequence,
        status.sequence_changed_at,
        status.detail,
    )


def _safe_probe(source: StreamSource, stream_name: str) -> Probe:
    # Runs in a worker thread: no ORM access here, and never raises.
    try:
        return source.probe(stream_name)
    except Exception as exc:  # noqa: BLE001 - one bad probe must not stop the cycle
        return Probe(False, False, None, None, f"{type(exc).__name__}: {exc}")


def run_cycle(source: StreamSource, now: datetime, max_workers: int = 8) -> int:
    """Probe all active recorders in parallel and write their statuses.

    Returns the number of probed recorders. Inactive recorders are set to
    unknown (and lose live_since) without being probed.
    """
    stale_factor = MonitorSettings.load().stale_factor
    recorders = list(Recorder.objects.select_related("status"))
    for recorder in recorders:
        if not hasattr(recorder, "status"):
            recorder.status = RecorderStatus.objects.create(recorder=recorder)

    active = [r for r in recorders if r.active]
    for recorder in recorders:
        if not recorder.active:
            status = recorder.status
            status.state = RecorderStatus.UNKNOWN
            status.live_since = None
            status.detail = "Recorder inactive"
            status.save(update_fields=["state", "live_since", "detail"])

    if not active:
        return 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        probes = list(pool.map(lambda r: _safe_probe(source, r.stream_name), active))

    for recorder, probe in zip(active, probes):
        status = recorder.status
        new = evaluate(_to_live_state(status), probe, now, stale_factor)
        status.state = new.state
        status.live_since = new.live_since
        status.media_sequence = new.media_sequence
        status.sequence_changed_at = new.sequence_changed_at
        status.detail = new.detail[:200]
        status.checked_at = now
        status.save()
    return len(active)
