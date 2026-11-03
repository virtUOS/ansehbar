# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prometheus exporter: ``GET /metrics`` (a scrape target, not an API route)."""
import hmac
from typing import ClassVar

from django.conf import settings
from django.http import Http404, HttpResponse
from rest_framework.views import APIView


def _esc(label_value):
    return str(label_value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_prometheus() -> str:
    """Render alarm, monitor, Opencast and recorder gauges (text format 0.0.4)."""
    from django.db.models import Max

    from alarms.delivery import _room
    from opencast.models import OpencastSyncState
    from opencast.sync import opencast_sync_enabled
    from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus

    lines = []

    def gauge(name, help_text, value=None, samples=None):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if samples is None:
            lines.append(f"{name} {int(value)}")
            return
        for labels, v in samples:
            lset = ",".join(f'{k}="{_esc(val)}"' for k, val in labels.items())
            lines.append(f"{name}{{{lset}}} {int(v)}")

    active = Recorder.objects.filter(active=True)

    if MonitorSettings.load().alarm_metrics_enabled:
        alarmed = set(
            Incident.objects.filter(
                kind=Incident.STREAM_MISSING,
                ended_at__isnull=True,
                alerted_at__isnull=False,
            ).values_list("recorder_id", flat=True)
        )
        gauge(
            "ansehbar_stream_missing_alarm",
            "1 while an alerted stream-missing incident is open",
            samples=[
                (
                    {"room": _room(r), "stream": r.stream_name},
                    1 if r.pk in alarmed else 0,
                )
                for r in active.exclude(alarm_mode=Recorder.ALARM_OFF).order_by("pk")
            ],
        )

    last_check = RecorderStatus.objects.filter(recorder__active=True).aggregate(
        t=Max("checked_at")
    )["t"]
    if last_check is not None:
        gauge(
            "ansehbar_monitor_last_check_timestamp_seconds",
            "Unix time of the last stream check of an active recorder",
            last_check.timestamp(),
        )

    enabled = opencast_sync_enabled()
    gauge("ansehbar_opencast_enabled", "1 if the Opencast sync is enabled", enabled)
    if enabled:
        last_success = OpencastSyncState.load().last_success_at
        if last_success is not None:
            gauge(
                "ansehbar_opencast_last_success_timestamp_seconds",
                "Unix time of the last successful Opencast sync",
                last_success.timestamp(),
            )

    counts = {RecorderStatus.LIVE: 0, RecorderStatus.OFFLINE: 0, RecorderStatus.UNKNOWN: 0}
    for state in active.values_list("status__state", flat=True):
        counts[state if state in counts else RecorderStatus.UNKNOWN] += 1
    gauge(
        "ansehbar_recorders",
        "Active recorders by state",
        samples=[({"state": s}, n) for s, n in counts.items()],
    )
    return "\n".join(lines) + "\n"


class MetricsView(APIView):
    """Token-guarded Prometheus exporter. The bearer token (``METRICS_TOKEN``)
    is checked by hand: a scraper has neither session nor OIDC token, and DRF
    authentication would pull in CSRF handling we do not want here."""

    permission_classes: ClassVar = []
    authentication_classes: ClassVar = []

    def get(self, request):
        token = settings.METRICS_TOKEN
        if not token:
            raise Http404()
        header = request.META.get("HTTP_AUTHORIZATION", "")
        # Bytes: compare_digest rejects non-ASCII str with TypeError (500).
        if not hmac.compare_digest(header.encode(), f"Bearer {token}".encode()):
            return HttpResponse(status=401)
        return HttpResponse(
            render_prometheus(),
            content_type="text/plain; version=0.0.4; charset=utf-8",
        )
