# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.db import models

from recorders.models import Recorder


class ScheduledEvent(models.Model):
    """Mirror of a scheduled Opencast event; ansehBAR never writes it back."""

    identifier = models.CharField(max_length=128, unique=True)
    recorder = models.ForeignKey(
        Recorder, on_delete=models.CASCADE, related_name="events"
    )
    title = models.CharField(max_length=300, blank=True)
    series = models.CharField(max_length=300, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["recorder", "start"])]

    def __str__(self):
        return f"{self.title or self.identifier} ({self.start:%Y-%m-%d %H:%M})"


class OpencastSyncState(models.Model):
    """Singleton (pk=1); use OpencastSyncState.load()."""

    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    @classmethod
    def load(cls) -> "OpencastSyncState":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
