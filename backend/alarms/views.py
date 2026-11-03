# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import uuid

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.permissions import HasAccess
from alarms.models import AlarmRecipient, SentNotification
from alarms.serializers import AlarmRecipientSerializer


class AlarmRecipientViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasAccess]
    serializer_class = AlarmRecipientSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return AlarmRecipient.objects.select_related("user")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.get_username())

    @action(detail=False, methods=["post"])
    def test(self, request):
        """Queue one test mail per active recipient; the monitor delivers it."""
        batch = uuid.uuid4()
        recipients = AlarmRecipient.objects.filter(active=True)
        SentNotification.objects.bulk_create(
            SentNotification(
                key=f"test:{batch}:email:{r.email}",
                channel=SentNotification.EMAIL,
                kind=SentNotification.TEST,
                recipient=r.email,
            )
            for r in recipients
        )
        return Response({"queued": recipients.count()}, status=status.HTTP_202_ACCEPTED)
