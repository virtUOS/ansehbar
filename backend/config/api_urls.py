# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""DRF routes under /api/ (whoami and auth endpoints live in config.urls)."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from accounts.views import InvitationViewSet, UserSearchViewSet
from recorders.views import MonitorHealthView, MonitorSettingsView, RecorderViewSet

router = DefaultRouter()
router.include_root_view = False
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("users", UserSearchViewSet, basename="user")
router.register("recorders", RecorderViewSet, basename="recorder")

urlpatterns = [
    path("monitor/health/", MonitorHealthView.as_view(), name="monitor-health"),
    path("settings/monitor/", MonitorSettingsView.as_view(), name="monitor-settings"),
    *router.urls,
]
