# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Deliver stream alarms and all-clears by e-mail (called by the monitor).

Idempotent across restarts: every message has a unique ``SentNotification.key``
and incidents are marked with conditional updates, so a second run (or a
parallel one) creates nothing twice.
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import formats, timezone, translation
from django.utils.translation import gettext as _

from alarms.models import AlarmRecipient, SentNotification
from recorders.alarm_rules import alarm_due
from recorders.incidents import STABLE_SECONDS
from recorders.models import Incident, MonitorSettings

logger = logging.getLogger(__name__)

# After this many failed attempts a message stays in the log with last_error.
MAX_ATTEMPTS = 5


def deliver_alarms(now: datetime) -> None:
    """Create due alarms and all-clears, then send pending messages; never raises."""
    try:
        monitor_settings = MonitorSettings.load()
    except Exception:
        logger.exception("loading monitor settings for alarms failed")
        return
    for phase in (_queue_alarms, _queue_all_clears):
        try:
            phase(monitor_settings, now)
        except Exception:
            logger.exception("%s failed", phase.__name__)
    try:
        _send_pending(now)
    except Exception:
        logger.exception("sending notifications failed")


def _queue_alarms(monitor_settings: MonitorSettings, now: datetime) -> None:
    candidates = Incident.objects.filter(
        ended_at__isnull=True, alerted_at__isnull=True
    ).select_related("recorder", "event")
    for incident in candidates:
        try:
            if not alarm_due(incident, monitor_settings, now):
                continue
            with transaction.atomic():
                marked = Incident.objects.filter(
                    pk=incident.pk, alerted_at__isnull=True
                ).update(alerted_at=now)
                if marked and monitor_settings.alarm_email_enabled:
                    _queue(incident, SentNotification.ALARM)
        except Exception:
            logger.exception("queueing alarm for incident %s failed", incident.pk)


def _queue_all_clears(monitor_settings: MonitorSettings, now: datetime) -> None:
    candidates = Incident.objects.filter(
        alerted_at__isnull=False,
        all_clear_at__isnull=True,
        recovered=True,
        ended_at__lte=now - timedelta(seconds=STABLE_SECONDS),
    ).select_related("recorder", "event")
    for incident in candidates:
        try:
            with transaction.atomic():
                # Still closed and recovered: a flicker may have reopened it.
                marked = Incident.objects.filter(
                    pk=incident.pk,
                    all_clear_at__isnull=True,
                    recovered=True,
                    ended_at__isnull=False,
                ).update(all_clear_at=now)
                if marked and monitor_settings.alarm_email_enabled:
                    _queue(incident, SentNotification.ALL_CLEAR)
        except Exception:
            logger.exception("queueing all-clear for incident %s failed", incident.pk)


def _queue(incident: Incident, kind: str) -> None:
    """One message of ``kind`` per active recipient (rendered now)."""
    subject, body = _render_incident(incident, kind)
    for email in AlarmRecipient.objects.filter(active=True).values_list(
        "email", flat=True
    ):
        SentNotification.objects.get_or_create(
            key=f"incident:{incident.pk}:{kind}:{SentNotification.EMAIL}:{email}",
            defaults={
                "channel": SentNotification.EMAIL,
                "kind": kind,
                "incident": incident,
                "recipient": email,
                "subject": subject,
                "body": body,
            },
        )


def _send_pending(now: datetime) -> None:
    pending = SentNotification.objects.filter(
        sent_at__isnull=True, attempts__lt=MAX_ATTEMPTS
    ).order_by("created_at", "pk")
    for note in pending:
        fields = ["attempts", "sent_at", "last_error"]
        if note.kind == SentNotification.TEST and not note.subject:
            # Test messages are queued by the API without content.
            note.subject, note.body = _render_test()
            fields += ["subject", "body"]
        note.attempts += 1
        try:
            send_mail(
                note.subject,
                note.body,
                settings.DEFAULT_FROM_EMAIL,
                [note.recipient],
                fail_silently=False,
            )
        except Exception as exc:
            note.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            logger.warning(
                "sending %s failed (attempt %s): %s", note.key, note.attempts, exc
            )
        else:
            note.sent_at = now
            note.last_error = ""
        try:
            note.save(update_fields=fields)
        except Exception:
            logger.exception("recording delivery of %s failed", note.key)


def _room(recorder) -> str:
    """Mirrors displayName in frontend/src/recorders.ts."""
    return recorder.room_name.strip() or recorder.agent_id or recorder.stream_name


def _clock(value: datetime) -> str:
    return timezone.localtime(value).strftime("%H:%M")


def _render_incident(incident: Incident, kind: str) -> tuple[str, str]:
    recorder = incident.recorder
    event = incident.event
    room = _room(recorder)
    all_clear = kind == SentNotification.ALL_CLEAR
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    with translation.override(settings.ALARM_LANGUAGE):
        if all_clear:
            subject = _("[ansehBAR] Stream back: %(room)s") % {"room": room}
        else:
            subject = _("[ansehBAR] Stream missing: %(room)s") % {"room": room}
        context = {
            "all_clear": all_clear,
            "room": room,
            "stream": recorder.stream_name,
            "event": event,
            "date": event
            and formats.date_format(timezone.localtime(event.start), "SHORT_DATE_FORMAT"),
            "start": event and _clock(event.start),
            "end": event and _clock(event.end),
            "missing_since": _clock(incident.started_at),
            "back_since": incident.ended_at and _clock(incident.ended_at),
            "link": f"{base}/raum/{recorder.pk}",
        }
        body = render_to_string("alarms/incident.txt", context).strip() + "\n"
    return subject, body


def _render_test() -> tuple[str, str]:
    with translation.override(settings.ALARM_LANGUAGE):
        subject = _("[ansehBAR] Test alarm")
        body = render_to_string(
            "alarms/test.txt",
            {"link": settings.FRONTEND_BASE_URL.rstrip("/") + "/"},
        ).strip() + "\n"
    return subject, body
