# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from rest_framework import mixins, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import HasAccess
from recorders.models import MonitorSettings, Recorder
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
        context["url_template"] = MonitorSettings.load().url_template
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
