# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Access check: who may use ansehBAR at all.

Access is granted by (any of) the IdP group claim, the bootstrap list from the
environment, or an invitation. The group claim is a snapshot from the last
login, so revoking the group at the IdP takes effect at the next login.
"""
from django.conf import settings


def normalize_identifier(value: str) -> str:
    return (value or "").strip().casefold()


def _in_groups(user) -> bool:
    claims = user.claims if isinstance(getattr(user, "claims", None), dict) else {}
    groups = claims.get(settings.OIDC_GROUPS_CLAIM)
    if isinstance(groups, str):
        groups = [groups]
    if not isinstance(groups, (list, tuple)):
        return False
    return settings.ANSEHBAR_ACCESS_GROUP in groups


def has_access(user) -> bool:
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    if _in_groups(user):
        return True
    identifiers = {
        i
        for i in (
            normalize_identifier(user.get_username()),
            normalize_identifier(user.email),
        )
        if i
    }
    if not identifiers:
        return False
    bootstrap = {normalize_identifier(u) for u in settings.ANSEHBAR_BOOTSTRAP_USERS}
    if identifiers & bootstrap:
        return True
    from accounts.models import Invitation

    return Invitation.objects.filter(identifier__in=identifiers).exists()
