# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from opencast.sync import opencast_sync_enabled, opencast_url_insecure, sync_window
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus
from recorders.serializers import MonitorSettingsSerializer, RecorderSerializer


class RecorderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Recorders; only deactivated ones can be deleted. PUT is not offered."""

    permission_classes = [HasAccess]
    serializer_class = RecorderSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Recorder.objects.select_related("status")
        if self.request.query_params.get("active") == "1":
            qs = qs.filter(active=True)
        return qs

    def destroy(self, request, *args, **kwargs):
        recorder = self.get_object()
        if recorder.active:
            return Response(
                {"detail": _("Only deactivated recorders can be deleted.")}, status=409
            )
        with transaction.atomic():
            if recorder.agent_id:
                IgnoredAgent.objects.get_or_create(
                    agent_id=recorder.agent_id,
                    defaults={
                        "created_by": (
                            request.user.get_full_name() or request.user.get_username()
                        )[:150]
                    },
                )
            recorder.delete()
        return Response(status=204)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # One settings lookup per request instead of one per row.
        monitor_settings = MonitorSettings.load()
        context["url_template"] = monitor_settings.url_template
        context["grace_minutes"] = monitor_settings.missing_grace_minutes
        context["end_tolerance_minutes"] = monitor_settings.end_tolerance_minutes
        # Current time and end of the local day once per request; events
        # that matter (running or starting today) in a single query.
        now = timezone.now()
        local_now = timezone.localtime(now)
        day_end = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # The same query also covers tomorrow (local), for the preview.
        tomorrow_end = day_end + timedelta(days=1)
        events_by_recorder = defaultdict(list)
        for event in ScheduledEvent.objects.filter(end__gt=now, start__lt=tomorrow_end):
            events_by_recorder[event.recorder_id].append(event)
        # Latest ended event per recorder within the lookback window, plus
        # their incidents: two more queries, independent of the row count.
        window_start = sync_window(now, 0, settings.OPENCAST_LOOKBACK_DAYS)[0]
        last_events = {}
        for event in ScheduledEvent.objects.filter(
            end__lte=now, end__gte=window_start
        ).order_by("-end"):
            last_events.setdefault(event.recorder_id, event)
        incidents_by_event = defaultdict(list)
        for incident in Incident.objects.filter(
            event__in=[e.pk for e in last_events.values()],
            kind__in=[Incident.STREAM_MISSING, Incident.AUDIO_SILENT],
        ):
            incidents_by_event[incident.event_id].append(incident)
        # Open silences of running events, one query: recorder -> (event,
        # start); the serializer keeps it only for the recorder's current event.
        open_silences = {}
        for recorder_id, event_id, started_at in Incident.objects.filter(
            kind=Incident.AUDIO_SILENT,
            ended_at__isnull=True,
            event__start__lte=now,
            event__end__gt=now,
        ).order_by("started_at").values_list("recorder_id", "event_id", "started_at"):
            open_silences.setdefault(recorder_id, (event_id, started_at))
        context["open_silences"] = open_silences
        context["last_events"] = last_events
        context["incidents_by_event"] = incidents_by_event
        context["now"] = now
        context["day_end"] = day_end
        context["tomorrow_end"] = tomorrow_end
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
        monitor_settings = MonitorSettings.objects.filter(pk=1).first() or MonitorSettings()
        return Response(
            {
                "last_check": last_check,
                "now": timezone.now(),
                "interval_seconds": settings.MONITOR_INTERVAL_SECONDS,
                # For grouping the schedule into recording slots.
                "slots": {
                    "minutes": monitor_settings.slot_minutes,
                    "offset_minutes": monitor_settings.slot_offset_minutes,
                },
                "opencast": {
                    "enabled": opencast_sync_enabled(),
                    # Set but refused: plain http:// would expose the password.
                    "insecure_url": opencast_url_insecure(),
                    "last_success": sync_state.last_success_at if sync_state else None,
                    "sync_seconds": settings.OPENCAST_SYNC_SECONDS,
                    "last_attempt": sync_state.last_attempt_at if sync_state else None,
                    "error_kind": sync_state.last_error_kind if sync_state else "",
                    "requested": bool(sync_state and sync_state.sync_requested),
                },
            }
        )
