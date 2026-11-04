# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Session/identity endpoints for the SPA.

``logout_view`` and ``set_language`` come from basicbar-auth (wired by
``basicbar_auth.urls``); only ``whoami`` is the tool's own, because it adds
the tool's feature flags to the shared payload.
"""
from basicbar_auth.views import whoami_payload
from basicbar_integrations import ai, translation_service
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.utils.translation import gettext as _
from rest_framework import mixins, serializers, viewsets
from rest_framework.response import Response

from accounts.access import has_access, normalize_identifier
from accounts.models import Invitation
from accounts.permissions import HasAccess
from recorders.models import MonitorSettings


def _tickets_enabled(user) -> bool:
    if not has_access(user):
        return False
    stored = MonitorSettings.objects.filter(pk=1).first()
    return bool(stored and stored.tickets_enabled)


def whoami(request):
    """Return the current session user (for the SPA to check login state),
    plus the feature flags the SPA needs before its first real request."""
    return JsonResponse(
        {
            **whoami_payload(request),
            "has_access": has_access(request.user),
            "access_contact": settings.ANSEHBAR_ACCESS_CONTACT,
            "ai_enabled": ai.is_enabled(),
            "tickets_enabled": _tickets_enabled(request.user),
            # Content-i18n config: the default/canonical authoring language and
            # whether machine-translation drafts are available, so the SPA can
            # decide which language to show/edit without a second round-trip.
            "content_default_language": settings.MODELTRANSLATION_DEFAULT_LANGUAGE,
            "content_translation_enabled": translation_service.is_enabled(),
        }
    )


class InvitationSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "identifier", "note", "created_by_name", "created_at"]
        read_only_fields = ["id", "created_by_name", "created_at"]

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.get_username() if obj.created_by else ""

    def validate_identifier(self, value):
        value = normalize_identifier(value)
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        if Invitation.objects.filter(identifier=value).exists():
            raise serializers.ValidationError(_("Already invited."))
        return value


class InvitationViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasAccess]
    serializer_class = InvitationSerializer
    pagination_class = None

    def get_queryset(self):
        return Invitation.objects.select_related("created_by")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class UserSearchSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ["id", "username", "email", "display_name"]

    def get_display_name(self, obj) -> str:
        return obj.get_full_name() or obj.get_username()


class UserSearchViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Search users by username, e-mail or name (max. 20 hits)."""

    permission_classes = [HasAccess]
    serializer_class = UserSearchSerializer
    pagination_class = None
    limit = 20

    def get_queryset(self):
        qs = get_user_model().objects.order_by("username")
        term = self.request.query_params.get("search", "").strip()
        for word in term.split():
            qs = qs.filter(
                Q(username__icontains=word)
                | Q(email__icontains=word)
                | Q(first_name__icontains=word)
                | Q(last_name__icontains=word)
            )
        return qs

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset()[: self.limit], many=True)
        return Response(serializer.data)
