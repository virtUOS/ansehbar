# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from recorders.validators import validate_stream_name, validate_url_template

DEFAULT_URL_TEMPLATE = (
    "https://streaming.example.org/live/{stream}/playlist.m3u8"
)


class Recorder(models.Model):
    # Empty means "room name missing" (recorder created from an Opencast agent).
    room_name = models.CharField(max_length=100, blank=True)
    # Case-sensitive on purpose (e.g. "cap-90-R12"); never lower-case it.
    stream_name = models.CharField(
        max_length=100, unique=True, validators=[validate_stream_name]
    )
    # Opencast agent id; NULL means not linked. Case-sensitive, never normalised.
    agent_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    active = models.BooleanField(default=True)
    needs_review = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["room_name"]

    def save(self, *args, **kwargs):
        if not self.agent_id:
            self.agent_id = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.room_name} ({self.stream_name})"


class RecorderStatus(models.Model):
    LIVE = "live"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    STATE_CHOICES = [(LIVE, "live"), (OFFLINE, "offline"), (UNKNOWN, "unknown")]

    recorder = models.OneToOneField(
        Recorder, on_delete=models.CASCADE, related_name="status"
    )
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=UNKNOWN)
    live_since = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    media_sequence = models.BigIntegerField(null=True, blank=True)
    sequence_changed_at = models.DateTimeField(null=True, blank=True)
    detail = models.CharField(max_length=200, blank=True)
    # Raw Opencast agent state; "" = never seen.
    agent_state = models.CharField(max_length=20, blank=True)
    agent_updated_at = models.DateTimeField(null=True, blank=True)
    offline_since = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.recorder.stream_name}: {self.state}"


class MonitorSettings(models.Model):
    """Singleton (pk=1); use MonitorSettings.load()."""

    url_template = models.CharField(
        max_length=300,
        default=DEFAULT_URL_TEMPLATE,
        validators=[validate_url_template],
    )
    stale_factor = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(2), MaxValueValidator(10)]
    )
    missing_grace_minutes = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(0), MaxValueValidator(30)]
    )

    @classmethod
    def load(cls) -> "MonitorSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class Incident(models.Model):
    """A gap in the stream during a scheduled event (recorded by the monitor)."""

    STREAM_MISSING = "stream_missing"
    KIND_CHOICES = [(STREAM_MISSING, "stream missing")]

    recorder = models.ForeignKey(
        Recorder, on_delete=models.CASCADE, related_name="incidents"
    )
    event = models.ForeignKey(
        "opencast.ScheduledEvent",
        on_delete=models.SET_NULL,
        null=True,
        related_name="incidents",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["started_at"]
        indexes = [models.Index(fields=["recorder", "started_at"])]

    def __str__(self):
        return f"{self.kind} {self.recorder_id} {self.started_at:%Y-%m-%d %H:%M}"
