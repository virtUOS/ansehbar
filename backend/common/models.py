# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared building blocks for the tool's domain models."""
from django.db import models


class TimeStampedModel(models.Model):
    """Adds created/updated timestamps; base for most domain models."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
