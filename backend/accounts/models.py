# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""User accounts, provisioned just-in-time on first OIDC login.

The OIDC machinery lives in basicbar-auth; this concrete model carries the
tool's own fields (basicbar ADR-0003). Add tool-specific fields here with
normal migrations.
"""
from basicbar_auth.models import AbstractBasicUser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from accounts.access import normalize_identifier


class User(AbstractBasicUser):
    """Application user (``subject``, ``claims`` and the UI ``language`` come
    from AbstractBasicUser)."""

    def __str__(self):
        return self.get_username()


class Invitation(models.Model):
    """Grants access to the person whose username or e-mail matches
    ``identifier`` (stored normalized: stripped and casefolded)."""

    identifier = models.CharField(max_length=254, unique=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["identifier"]

    def save(self, *args, **kwargs):
        self.identifier = normalize_identifier(self.identifier)
        if not self.identifier:
            raise ValidationError({"identifier": "Identifier must not be empty."})
        super().save(*args, **kwargs)

    def __str__(self):
        return self.identifier
