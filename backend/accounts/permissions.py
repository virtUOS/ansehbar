# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared DRF permissions."""
from rest_framework.permissions import BasePermission

from accounts.access import has_access


class IsAdmin(BasePermission):
    """Site administrators only — Django staff or superusers. Staff is
    granted via the OIDC admin group (basicbar_auth.oidc)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and (user.is_staff or user.is_superuser)
        )


class HasAccess(BasePermission):
    """Only people admitted by IdP group, bootstrap list or invitation."""

    def has_permission(self, request, view):
        return has_access(request.user)
