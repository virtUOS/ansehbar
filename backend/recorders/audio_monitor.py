# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Audio pass: measure live streams during events, track silence incidents."""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from opencast.models import ScheduledEvent
from recorders.alarm_rules import silence_counts_from
from recorders.models import AudioSample, Incident, MonitorSettings, Recorder, RecorderStatus
from recorders.monitor import _save
from streams.audio import AudioMeasurement
from streams.sources import StreamSource

# Stored levels never go below this (ffmpeg reports -inf for digital silence;
# neither the database nor the JSON API should see -Infinity).
AUDIO_FLOOR_DB = -91.0
NO_AUDIO_TRACK = "no audio track"
# A silent reading after a longer gap without a successful measurement starts
# a new silence: nobody knows whether there was sound in between.
MAX_MEASUREMENT_GAP = timedelta(minutes=5)


def _running_events(now: datetime) -> dict[int, ScheduledEvent]:
    """Recorder id -> earliest event with start <= now < end."""
    running = {}
    for event in ScheduledEvent.objects.filter(start__lte=now, end__gt=now).order_by(
        "start", "pk"
    ):
        running.setdefault(event.recorder_id, event)
    return running


def _targets(now: datetime) -> tuple[list[tuple[Recorder, ScheduledEvent]], set[int]]:
    """Active, live recorders with a running event, and the ids of those to hold.

    Held: active recorders with a running event whose stream state is
    unknown. They are not measured, but like after a failed measurement
    their silence state stays as it is.
    """
    running = _running_events(now)
    targets = []
    held = set()
    for recorder in Recorder.objects.filter(active=True).select_related("status"):
        if not hasattr(recorder, "status"):
            continue
        event = running.get(recorder.pk)
        if event is None:
            continue
        if recorder.status.state == RecorderStatus.LIVE:
            targets.append((recorder, event))
        elif recorder.status.state == RecorderStatus.UNKNOWN:
            held.add(recorder.pk)
    return targets, held


def _safe_measure(measure, source: StreamSource, stream_name: str) -> AudioMeasurement:
    # Runs in a worker thread: no ORM access here, and never raises.
    try:
        return measure(source.playback_url(stream_name))
    except Exception as exc:  # noqa: BLE001 - one bad measurement must not stop the pass
        return AudioMeasurement(False, None, f"{type(exc).__name__}: {exc}"[:200])


def _write(status: RecorderStatus, event: ScheduledEvent, result: AudioMeasurement,
           threshold: int, now: datetime) -> bool:
    """Store one measurement; True if it measured sound."""
    if not result.ok:
        # A failed measurement is no silence: the silence state stays as it is.
        status.audio_detail = result.detail[:200]
        _save(status, ["audio_detail"])
        return False
    level = None if result.level_db is None else max(result.level_db, AUDIO_FLOOR_DB)
    AudioSample.objects.create(
        recorder_id=status.recorder_id, event=event, measured_at=now, level_db=level
    )
    status.audio_level_db = level
    sound = level is not None and level >= threshold
    previous = status.audio_checked_at
    status.audio_checked_at = now
    if not sound:
        if previous is None or previous < now - MAX_MEASUREMENT_GAP:
            # Too long without a measurement: the silence starts anew, and an
            # incident of the old one ends with its last silent measurement.
            status.silent_since = now
            for incident in Incident.objects.filter(
                recorder_id=status.recorder_id,
                kind=Incident.AUDIO_SILENT,
                ended_at__isnull=True,
            ):
                incident.ended_at = incident.silent_until or now
                incident.save(update_fields=["ended_at"])
        else:
            status.silent_since = status.silent_since or now
        status.audio_detail = NO_AUDIO_TRACK if level is None else ""
    else:
        status.silent_since = None
        status.audio_detail = ""
        # Only within the event (the measurement may finish after its end).
        ScheduledEvent.objects.filter(
            pk=event.pk, first_audio_at__isnull=True, end__gt=now
        ).update(first_audio_at=now)
    _save(
        status,
        ["audio_level_db", "audio_checked_at", "audio_detail", "silent_since"],
    )
    return sound


def run_audio_pass(
    measure: Callable[[str], AudioMeasurement],
    source: StreamSource,
    now_fn: Callable[[], datetime] = timezone.now,
    max_workers: int = 4,
) -> int:
    """Measure all live recorders with a running event; returns their number.

    Only the audio fields and silent_since of the statuses are written; the
    stream cycle and the Opencast sync own the other fields.
    """
    started = now_fn()  # only for choosing the targets
    targets, held = _targets(started)
    # Never measured first, then least recently measured: a fair rotation.
    targets.sort(
        key=lambda t: (
            t[0].status.audio_checked_at is not None,
            t[0].status.audio_checked_at or started,
        )
    )
    results = []
    if targets:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(
                pool.map(
                    lambda t: _safe_measure(measure, source, t[0].stream_name), targets
                )
            )

    now = now_fn()  # after the measurements
    threshold = MonitorSettings.load().silence_threshold_db
    sound_ids = {
        recorder.pk
        for (recorder, event), result in zip(targets, results)
        if _write(recorder.status, event, result, threshold, now)
    }

    # Not measured (offline, no event, inactive): no silence state. An unknown
    # stream state is no news about the sound: that state stays.
    keep_ids = [recorder.pk for recorder, _ in targets] + sorted(held)
    stale = RecorderStatus.objects.exclude(recorder_id__in=keep_ids).filter(
        Q(silent_since__isnull=False) | Q(audio_level_db__isnull=False)
    )
    for status in stale:
        status.silent_since = None
        status.audio_level_db = None
        _save(status, ["silent_since", "audio_level_db"])

    update_audio_incidents(now, sound_ids)
    return len(targets)


def update_audio_incidents(now: datetime, sound_ids: set[int] = frozenset()) -> None:
    """Open, extend and close audio_silent incidents from the stored statuses.

    sound_ids: recorders measured with sound in this pass. Only those count as
    recovered; a silence state cleared for any other reason (e.g. the stream
    dropped while the pass measured) ends the incident now, not recovered.
    An unknown stream state changes nothing (like a failed measurement).
    Silence counts only from the room's stream alarm threshold on.
    """
    settings = MonitorSettings.load()
    log_after = timedelta(minutes=settings.silence_log_minutes)
    running = _running_events(now)
    recorders = {r.pk: r for r in Recorder.objects.select_related("status")}
    open_incidents = list(
        Incident.objects.filter(
            kind=Incident.AUDIO_SILENT, ended_at__isnull=True
        ).select_related("event")
    )
    with transaction.atomic():
        open_keys = set()
        for incident in open_incidents:
            event = incident.event
            recorder = recorders.get(incident.recorder_id)
            status = getattr(recorder, "status", None) if recorder else None
            if event is None or event.end <= now:
                incident.ended_at = min(event.end, now) if event else now
                fields = ["ended_at"]
            elif (
                recorder is None
                or not recorder.active
                or status is None
                or status.state == RecorderStatus.OFFLINE
            ):
                incident.ended_at = now
                fields = ["ended_at"]
            elif status.state == RecorderStatus.UNKNOWN:
                # No news about the sound: the incident stays as it is.
                open_keys.add((incident.recorder_id, incident.event_id))
                continue
            elif status.silent_since is None and incident.recorder_id in sound_ids:
                # Sound is back: the incident ends with that measurement.
                incident.ended_at = status.audio_checked_at or now
                incident.recovered = True
                fields = ["ended_at", "recovered"]
            elif status.silent_since is None:
                # Silence state cleared without a sound measurement (not
                # measured in this pass, e.g. the stream was down): no recovery.
                incident.ended_at = now
                fields = ["ended_at"]
            else:
                incident.silent_until = status.audio_checked_at
                open_keys.add((incident.recorder_id, incident.event_id))
                fields = ["silent_until"]
            incident.save(update_fields=fields)

        new = []
        for recorder in recorders.values():
            status = getattr(recorder, "status", None)
            event = running.get(recorder.pk)
            if (
                not recorder.active
                or status is None
                or status.state == RecorderStatus.OFFLINE
                or event is None
                or status.silent_since is None
                or status.audio_checked_at is None
                or (recorder.pk, event.pk) in open_keys
            ):
                continue
            start = max(
                status.silent_since,
                silence_counts_from(event, recorder.alarm_mode, settings),
            )
            if status.audio_checked_at - start >= log_after:
                new.append(
                    Incident(
                        recorder=recorder,
                        event=event,
                        kind=Incident.AUDIO_SILENT,
                        started_at=start,
                        silent_until=status.audio_checked_at,
                    )
                )
        Incident.objects.bulk_create(new)
