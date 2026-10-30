# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""DRF routes under /api/ (whoami and auth endpoints live in config.urls)."""
from rest_framework.routers import DefaultRouter

from accounts.views import InvitationViewSet, UserSearchViewSet

router = DefaultRouter()
router.include_root_view = False
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("users", UserSearchViewSet, basename="user")

urlpatterns = router.urls
