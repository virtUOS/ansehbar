# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Record stream gaps during scheduled events as Incident rows."""
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import transaction

from opencast.models import ScheduledEvent
from recorders.missing import missing_since
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus

# A stream that drops again within this many seconds of coming back did not
# return stably: the previous incident is reopened instead of a new one.
STABLE_SECONDS = 60


def update_incidents(now: datetime) -> None:
    """Open, close and finish incidents from the statuses the cycle just wrote.

    Reads settings, active recorders with status, running events, open
    incidents with their events and recently recovered incidents (five
    queries, independent of the number of recorders); closing and reopening
    write one update per incident, opening one bulk insert.
    """
    monitor_settings = MonitorSettings.load()
    grace = timedelta(minutes=monitor_settings.missing_grace_minutes)
    end_tolerance = timedelta(minutes=monitor_settings.end_tolerance_minutes)
    recorders = list(
        Recorder.objects.filter(active=True).select_related("status")
    )
    running = defaultdict(list)  # recorder id -> running events by start
    for event in ScheduledEvent.objects.filter(start__lte=now, end__gt=now):
        running[event.recorder_id].append(event)
    open_incidents = list(
        Incident.objects.filter(ended_at__isnull=True).select_related("event")
    )

    state_by_recorder = {
        r.pk: r.status.state for r in recorders if hasattr(r, "status")
    }
    active_ids = {r.pk for r in recorders}
    open_keys = set()
    with transaction.atomic():
        for incident in open_incidents:
            event = incident.event
            if event is None:
                # Event vanished from the schedule; the end is unknown.
                incident.ended_at = now
            elif event.end <= now:
                incident.ended_at = event.end
            elif incident.recorder_id not in active_ids:
                # Recorder deactivated: no longer monitored, the gap ends now.
                incident.ended_at = now
            elif state_by_recorder.get(incident.recorder_id) == RecorderStatus.LIVE:
                # The stream came back.
                incident.ended_at = now
                incident.recovered = True
                incident.save(update_fields=["ended_at", "recovered"])
                continue
            else:
                # Unknown (or offline) keeps it open.
                open_keys.add((incident.recorder_id, incident.event_id))
                continue
            incident.save(update_fields=["ended_at"])

        # Latest incident per (recorder, event) that recovered too recently
        # to count as a stable return.
        recently_recovered = {}
        for incident in Incident.objects.filter(
            recovered=True,
            ended_at__gte=now - timedelta(seconds=STABLE_SECONDS),
            event__isnull=False,
        ).order_by("ended_at", "pk"):
            recently_recovered[(incident.recorder_id, incident.event_id)] = incident

        new = []
        for recorder in recorders:
            if not hasattr(recorder, "status"):
                continue
            current = running[recorder.pk][0] if running.get(recorder.pk) else None
            since = missing_since(
                recorder.active,
                recorder.status.state,
                recorder.status.offline_since,
                current,
                now,
                grace,
                end_tolerance,
            )
            key = (recorder.pk, current.pk) if current else None
            if since is None or key in open_keys:
                continue
            flickered = recently_recovered.get(key)
            if flickered is not None:
                flickered.ended_at = None
                flickered.recovered = False
                flickered.save(update_fields=["ended_at", "recovered"])
                continue
            new.append(
                Incident(
                    recorder=recorder,
                    event=current,
                    kind=Incident.STREAM_MISSING,
                    started_at=since,
                )
            )
        Incident.objects.bulk_create(new)
