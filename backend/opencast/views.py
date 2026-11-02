# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from opencast.models import OpencastSyncState


class OpencastSyncRequestView(APIView):
    """Ask the monitor for an Opencast sync soon. Read-only towards Opencast."""

    permission_classes = [HasAccess]

    def post(self, request):
        if not settings.OPENCAST_URL:
            return Response({"detail": _("Opencast is not configured.")}, status=409)
        state = OpencastSyncState.load()
        state.requested_at = timezone.now()
        state.save(update_fields=["requested_at"])
        return Response({"requested_at": state.requested_at}, status=202)
