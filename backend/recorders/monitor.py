# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""One monitoring cycle: probe active recorders, persist their status."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from django.db import DatabaseError, transaction

from recorders.models import MonitorSettings, Recorder, RecorderStatus
from streams.sources import LiveState, Probe, StreamSource, evaluate

logger = logging.getLogger(__name__)

# Status fields written by the monitor cycle; agent_* belong to the Opencast sync.
CYCLE_FIELDS = [
    "state",
    "live_since",
    "offline_since",
    "media_sequence",
    "sequence_changed_at",
    "detail",
    "checked_at",
]


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


def _save(status: RecorderStatus, fields: list[str]) -> None:
    """Save a status; a recorder deleted meanwhile must not abort the cycle."""
    try:
        # Savepoint: a failed write must not break an outer transaction.
        with transaction.atomic():
            status.save(update_fields=fields)
    except DatabaseError:
        # save(update_fields=...) raises if the row is gone (recorder deleted).
        logger.info("status of recorder %s not saved (deleted?)", status.recorder_id)


def run_cycle(source: StreamSource, now: datetime, max_workers: int = 8) -> int:
    """Probe all active recorders in parallel and write their statuses.

    Returns the number of probed recorders. Inactive recorders are set to
    unknown (and lose live_since/offline_since) without being probed.
    """
    stale_factor = MonitorSettings.load().stale_factor
    recorders = list(Recorder.objects.select_related("status"))
    for recorder in recorders:
        if not hasattr(recorder, "status"):
            try:
                with transaction.atomic():
                    recorder.status = RecorderStatus.objects.create(recorder=recorder)
            except DatabaseError:
                # Deleted since loading (or the sync created the status first).
                logger.info("no status for recorder %s (deleted?)", recorder.pk)
    recorders = [r for r in recorders if hasattr(r, "status")]

    active = [r for r in recorders if r.active]
    for recorder in recorders:
        if not recorder.active:
            status = recorder.status
            status.state = RecorderStatus.UNKNOWN
            status.live_since = None
            status.offline_since = None
            status.detail = "Recorder inactive"
            _save(status, ["state", "live_since", "offline_since", "detail"])

    if not active:
        return 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        probes = list(pool.map(lambda r: _safe_probe(source, r.stream_name), active))

    for recorder, probe in zip(active, probes):
        status = recorder.status
        new = evaluate(_to_live_state(status), probe, now, stale_factor)
        if new.state == RecorderStatus.OFFLINE:
            # Keep the start across a single unknown probe (offline -> unknown
            # -> offline); only live resets it.
            if status.offline_since is None:
                status.offline_since = now
        elif new.state == RecorderStatus.LIVE:
            status.offline_since = None
        # unknown: offline_since stays as it is
        status.state = new.state
        status.live_since = new.live_since
        status.media_sequence = new.media_sequence
        status.sequence_changed_at = new.sequence_changed_at
        status.detail = new.detail[:200]
        status.checked_at = now
        # Only the fields the cycle owns: the Opencast sync (own thread) may
        # have written agent_state/agent_updated_at since the statuses were loaded.
        _save(status, CYCLE_FIELDS)
    return len(active)
