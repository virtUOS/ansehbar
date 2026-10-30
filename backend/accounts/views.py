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
from django.http import JsonResponse


def whoami(request):
    """Return the current session user (for the SPA to check login state),
    plus the feature flags the SPA needs before its first real request."""
    return JsonResponse(
        {
            **whoami_payload(request),
            "ai_enabled": ai.is_enabled(),
            # Content-i18n config: the default/canonical authoring language and
            # whether machine-translation drafts are available, so the SPA can
            # decide which language to show/edit without a second round-trip.
            "content_default_language": settings.MODELTRANSLATION_DEFAULT_LANGUAGE,
            "content_translation_enabled": translation_service.is_enabled(),
        }
    )
