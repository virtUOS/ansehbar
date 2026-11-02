# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from opencast.models import OpencastSyncState, ScheduledEvent
from recorders.models import MonitorSettings, Recorder, RecorderStatus
from recorders.serializers import MonitorSettingsSerializer, RecorderSerializer


class RecorderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Recorders; no delete (deactivate via active=false). PUT is not offered."""

    permission_classes = [HasAccess]
    serializer_class = RecorderSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Recorder.objects.select_related("status")
        if self.request.query_params.get("active") == "1":
            qs = qs.filter(active=True)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # One settings lookup per request instead of one per row.
        monitor_settings = MonitorSettings.load()
        context["url_template"] = monitor_settings.url_template
        context["grace_minutes"] = monitor_settings.missing_grace_minutes
        # Current time and end of the local day once per request; events
        # that matter (running or starting today) in a single query.
        now = timezone.now()
        local_now = timezone.localtime(now)
        day_end = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        events_by_recorder = defaultdict(list)
        for event in ScheduledEvent.objects.filter(end__gt=now, start__lt=day_end):
            events_by_recorder[event.recorder_id].append(event)
        context["now"] = now
        context["day_end"] = day_end
        context["events_by_recorder"] = events_by_recorder
        return context


class MonitorSettingsView(APIView):
    permission_classes = [HasAccess]

    def get(self, request):
        return Response(MonitorSettingsSerializer(MonitorSettings.load()).data)

    def put(self, request):
        serializer = MonitorSettingsSerializer(MonitorSettings.load(), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MonitorHealthView(APIView):
    """Heartbeat of the monitor process: when did it last check a recorder?

    The client compares `last_check` against the server's `now` (not the
    browser clock) to detect a stalled or stopped monitor.
    """

    permission_classes = [HasAccess]

    def get(self, request):
        last_check = RecorderStatus.objects.filter(recorder__active=True).aggregate(
            last=Max("checked_at")
        )["last"]
        # filter().first(): a GET must not create the singleton row.
        sync_state = OpencastSyncState.objects.filter(pk=1).first()
        return Response(
            {
                "last_check": last_check,
                "now": timezone.now(),
                "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
                "opencast": {
                    "enabled": bool(settings.OPENCAST_URL),
                    "last_success": sync_state.last_success_at if sync_state else None,
                    "sync_seconds": settings.OPENCAST_SYNC_SECONDS,
                    "last_attempt": sync_state.last_attempt_at if sync_state else None,
                    "error_kind": sync_state.last_error_kind if sync_state else "",
                    "requested": bool(sync_state and sync_state.sync_requested),
                },
            }
        )
