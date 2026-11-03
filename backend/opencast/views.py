# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from opencast.sync import opencast_sync_enabled
from recorders.history import _iso, incident_data
from recorders.models import AudioSample, Incident, MonitorSettings

# "Sync now" right after an attempt adds nothing: ignore it for this long.
SYNC_REQUEST_MIN_SECONDS = 10


class OpencastSyncRequestView(APIView):
    """Ask the monitor for an Opencast sync soon. Read-only towards Opencast."""

    permission_classes = [HasAccess]

    def post(self, request):
        # Same predicate as the monitor: otherwise the request would stay
        # pending forever (e.g. plain http:// in production).
        if not opencast_sync_enabled():
            return Response({"detail": _("Opencast is not configured.")}, status=409)
        state = OpencastSyncState.load()
        now = timezone.now()
        recent = state.last_attempt_at is not None and (
            (now - state.last_attempt_at).total_seconds() < SYNC_REQUEST_MIN_SECONDS
        )
        # Repeated clicks: a pending request or a fresh attempt already covers it.
        if not state.sync_requested and not recent:
            state.requested_at = now
            state.save(update_fields=["requested_at"])
        return Response({"requested_at": state.requested_at}, status=202)


class EventDetailView(APIView):
    """One event with its incidents and level samples (for the timeline)."""

    permission_classes = [HasAccess]

    def get(self, request, pk):
        event = get_object_or_404(ScheduledEvent, pk=pk)
        incidents = Incident.objects.filter(event=event).order_by("started_at", "id")
        samples = AudioSample.objects.filter(
            event=event, measured_at__gte=event.start, measured_at__lte=event.end
        ).order_by("measured_at", "id")
        return Response(
            {
                "id": event.pk,
                "recorder_id": event.recorder_id,
                "title": event.title,
                "series": event.series,
                "start": _iso(event.start),
                "end": _iso(event.end),
                "opencast_status": event.opencast_status,
                "first_audio_at": _iso(event.first_audio_at),
                "threshold_db": MonitorSettings.load().silence_threshold_db,
                "incidents": [incident_data(i) for i in incidents],
                "samples": [
                    {
                        "t": _iso(s.measured_at),
                        "db": None if s.level_db is None else round(s.level_db, 1),
                    }
                    for s in samples
                ],
            }
        )


class IgnoredAgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IgnoredAgent
        fields = ["id", "agent_id", "created_at", "created_by"]
        read_only_fields = fields


class IgnoredAgentViewSet(
    mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Agents the sync skips; deleting an entry lets the agent return."""

    permission_classes = [HasAccess]
    serializer_class = IgnoredAgentSerializer
    queryset = IgnoredAgent.objects.all()
    pagination_class = None
