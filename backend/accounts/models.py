# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""User accounts, provisioned just-in-time on first OIDC login.

The OIDC machinery lives in basicbar-auth; this concrete model carries the
tool's own fields (basicbar ADR-0003). Add tool-specific fields here with
normal migrations.
"""
from basicbar_auth.models import AbstractBasicUser


class User(AbstractBasicUser):
    """Application user (``subject``, ``claims`` and the UI ``language`` come
    from AbstractBasicUser)."""

    def __str__(self):
        return self.get_username()
