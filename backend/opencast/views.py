# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from opencast.models import IgnoredAgent, OpencastSyncState
from opencast.sync import opencast_sync_enabled


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
