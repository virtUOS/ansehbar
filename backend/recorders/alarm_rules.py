# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""When is a stream incident worth an alarm?

Pure rules, no I/O. Callers should ``select_related("recorder", "event")``.
"""
from datetime import datetime, timedelta

from django.utils import timezone

from .models import Incident, MonitorSettings, Recorder


def slot_start(at: datetime, minutes: int, offset_minutes: int) -> datetime:
    """Start of the recording slot containing ``at`` (aware, local time).

    Mirrors ``slotOf`` in frontend/src/recorders.ts: slots begin
    ``offset_minutes`` after local midnight and are ``minutes`` long; before
    the offset we are in the last slot of the previous day.
    """
    local = timezone.localtime(at)
    minute_of_day = local.hour * 60 + local.minute
    index = (minute_of_day - offset_minutes) // minutes  # floor, may be -1
    midnight = datetime(local.year, local.month, local.day)  # naive
    naive = midnight + timedelta(minutes=offset_minutes + index * minutes)
    return timezone.make_aware(naive)


def alarm_threshold(event, mode: str, settings: MonitorSettings) -> datetime | None:
    """Earliest moment a missing stream may alarm for this event."""
    if mode == Recorder.ALARM_OFF:
        return None
    exact = event.start + timedelta(minutes=settings.missing_grace_minutes)
    if mode == Recorder.ALARM_GRID:
        slot = slot_start(event.start, settings.slot_minutes, settings.slot_offset_minutes)
        grid = slot + timedelta(
            minutes=settings.ct_minutes + settings.ct_tolerance_minutes
        )
        return max(exact, grid)
    return exact


def alarm_due(incident: Incident, settings: MonitorSettings, now: datetime) -> bool:
    """True if this open incident should alarm now."""
    event = incident.event
    if incident.ended_at is not None or event is None:
        return False
    if not (event.start <= now < event.end):
        return False
    recorder = incident.recorder
    if not recorder.active:
        return False
    threshold = alarm_threshold(event, recorder.alarm_mode, settings)
    if threshold is None:
        return False
    return now >= max(threshold, incident.started_at)


def audio_alarm_due(
    incident: Incident,
    settings: MonitorSettings,
    now: datetime,
    alerted_events: set[int],
) -> bool:
    """True if this open ``audio_silent`` incident should alarm now.

    Only the first long silence per event alarms: ``alerted_events`` holds the
    events in which an audio incident has already alerted. Silence is measured
    up to the last silent measurement, so failed measurements never extend it.
    """
    event = incident.event
    if incident.ended_at is not None or event is None:
        return False
    if not (event.start <= now < event.end):
        return False
    recorder = incident.recorder
    if not recorder.active or recorder.alarm_mode == Recorder.ALARM_OFF:
        return False
    if event.pk in alerted_events or incident.silent_until is None:
        return False
    return incident.silent_until - incident.started_at >= timedelta(
        minutes=settings.silence_alarm_minutes
    )
