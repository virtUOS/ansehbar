# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Retention: delete old level samples and old history."""
from datetime import datetime, timedelta

from django.db.models import Q

from alarms.models import SentNotification
from opencast.models import ScheduledEvent
from recorders.models import AudioSample, Incident, MonitorSettings


def prune_history(now: datetime) -> dict[str, int]:
    """Delete rows older than the configured retention; return the counts.

    Order matters: events go last so no incident is left without its event.
    """
    config = MonitorSettings.load()
    sample_cutoff = now - timedelta(days=config.sample_retention_days)
    history_cutoff = now - timedelta(days=config.history_retention_days)
    samples = AudioSample.objects.filter(measured_at__lt=sample_cutoff).delete()[0]
    notifications = SentNotification.objects.filter(
        created_at__lt=history_cutoff
    ).delete()[0]
    # An incident of an event that ended after the cutoff stays with its event,
    # even if it started before the cutoff.
    incidents = (
        Incident.objects.filter(started_at__lt=history_cutoff)
        .filter(Q(event__isnull=True) | Q(event__end__lt=history_cutoff))
        .delete()[0]
    )
    # Deleting an event cascades to nothing else we count (samples are
    # SET_NULL), so the first element is the event count.
    events = ScheduledEvent.objects.filter(end__lt=history_cutoff).delete()[1].get(
        "opencast.ScheduledEvent", 0
    )
    return {
        "samples": samples,
        "incidents": incidents,
        "events": events,
        "notifications": notifications,
    }
