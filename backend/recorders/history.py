# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Problems and incident data of ended events, shared by tile and calendar."""

from datetime import date, datetime, timedelta

from rest_framework import serializers

from opencast.sync import _local_midnight
from recorders.models import Incident

_to_iso = serializers.DateTimeField().to_representation


def _iso(value):
    return None if value is None else _to_iso(value)


def recording_problems(event, incidents, now, silence_alarm_minutes: int) -> list:
    """Problems of an ended event: incident gaps, then the Opencast status."""
    problems = []
    significant = timedelta(minutes=silence_alarm_minutes)
    for incident in incidents:
        # Only the part within the event counts; an incident still open
        # on an ended event stops at the event end.
        began = max(incident.started_at, event.start)
        ended = min(incident.ended_at or event.end, event.end)
        if ended <= began:
            continue
        # Short silences stay stored (for the timeline), but only those
        # that alerted or reached the alarm time are a problem here.
        if (
            incident.kind == Incident.AUDIO_SILENT
            and incident.alerted_at is None
            and ended - began < significant
        ):
            continue
        seconds = (ended - began).total_seconds()
        problems.append(
            {
                "kind": incident.kind,
                "from": _to_iso(began),
                "to": _to_iso(ended),
                "minutes": max(1, round(seconds / 60)),
            }
        )
    status = event.opencast_status
    deadline = event.end + timedelta(minutes=30)
    # "Did not start/finish" only from a status Opencast delivered for this
    # event after the deadline; an older one (or one of an event deleted in
    # Opencast meanwhile) may simply be stale.
    seen_at = event.seen_at
    overdue = now >= deadline and seen_at is not None and seen_at >= deadline
    if status.endswith("PROCESSING_FAILURE"):
        problems.append({"kind": "processing_failed"})
    elif status.endswith("RECORDING_FAILURE"):
        problems.append({"kind": "recording_failed"})
    elif overdue and status.endswith("SCHEDULED"):
        problems.append({"kind": "not_started"})
    elif overdue and status.endswith(("RECORDING", "INGESTING")):
        problems.append({"kind": "not_finished"})
    return problems


def incident_data(incident) -> dict:
    return {
        "id": incident.pk,
        "kind": incident.kind,
        "started_at": _iso(incident.started_at),
        "ended_at": _iso(incident.ended_at),
        "recovered": incident.recovered,
        "alerted_at": _iso(incident.alerted_at),
        "all_clear_at": _iso(incident.all_clear_at),
        "silent_until": _iso(incident.silent_until),
    }


def calendar_range(day: date, days: int) -> tuple[datetime, datetime]:
    """Local midnight of `day` to local midnight `days` later (DST-correct)."""
    return _local_midnight(day), _local_midnight(day + timedelta(days=days))
