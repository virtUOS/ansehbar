# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from common.encryption import decrypt, encrypt
from recorders.gitlab_url import parse_project_url
from recorders.validators import validate_stream_name, validate_url_template

DEFAULT_URL_TEMPLATE = (
    "https://streaming.example.org/live/{stream}/playlist.m3u8"
)


class Recorder(models.Model):
    ALARM_EXACT = "exact"
    ALARM_GRID = "grid"
    ALARM_OFF = "off"
    ALARM_MODE_CHOICES = [
        (ALARM_EXACT, _("On time (Opencast start)")),
        (ALARM_GRID, _("Grid (c.t.)")),
        (ALARM_OFF, _("Off (log only)")),
    ]

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
    alarm_mode = models.CharField(
        max_length=5, choices=ALARM_MODE_CHOICES, default=ALARM_EXACT
    )
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
    # Audio level (written only by the audio monitor): last successful
    # measurement, its mean level and the start of the current silence.
    audio_level_db = models.FloatField(null=True, blank=True)
    audio_checked_at = models.DateTimeField(null=True, blank=True)
    audio_detail = models.CharField(max_length=200, blank=True)
    silent_since = models.DateTimeField(null=True, blank=True)

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
    # Recording slots for grouping the schedule: slots of `slot_minutes`
    # starting `slot_offset_minutes` after local midnight (default: 2-hour
    # slots at even hours).
    slot_minutes = models.PositiveSmallIntegerField(
        default=120, validators=[MinValueValidator(15), MaxValueValidator(480)]
    )
    slot_offset_minutes = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(479)]
    )
    # Alarm timing: c.t. offset after the slot start and tolerance after it;
    # tolerance for a stream ending shortly before the scheduled end.
    ct_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(0), MaxValueValidator(60)]
    )
    ct_tolerance_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(0), MaxValueValidator(30)]
    )
    end_tolerance_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(0), MaxValueValidator(30)]
    )
    alarm_email_enabled = models.BooleanField(default=True)
    alarm_metrics_enabled = models.BooleanField(default=True)
    # Silence detection: level below the threshold counts as silent; logged
    # after silence_log_minutes, alarmed after silence_alarm_minutes.
    silence_threshold_db = models.SmallIntegerField(
        default=-50, validators=[MinValueValidator(-90), MaxValueValidator(-20)]
    )
    silence_log_minutes = models.PositiveSmallIntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(30)]
    )
    silence_alarm_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(5), MaxValueValidator(120)]
    )
    # Retention: level samples vs. incidents, events and notifications.
    sample_retention_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    history_retention_days = models.PositiveSmallIntegerField(
        default=400, validators=[MinValueValidator(183), MaxValueValidator(3650)]
    )

    # GitLab project for tickets; the token is stored encrypted.
    gitlab_url = models.URLField(blank=True, max_length=500)
    gitlab_token = models.TextField(blank=True, default="")

    def gitlab_token_plain(self) -> str:
        return decrypt(self.gitlab_token)

    def set_gitlab_token(self, plain: str) -> None:
        self.gitlab_token = encrypt(plain)

    @property
    def tickets_enabled(self) -> bool:
        return bool(
            parse_project_url(self.gitlab_url) is not None and self.gitlab_token_plain()
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
    AUDIO_SILENT = "audio_silent"
    KIND_CHOICES = [
        (STREAM_MISSING, "stream missing"),
        (AUDIO_SILENT, "audio silent"),
    ]

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
    # Closed because the stream came back (not because the event ended).
    recovered = models.BooleanField(default=False)
    # When the incident became worth an alarm, independent of the channel.
    alerted_at = models.DateTimeField(null=True, blank=True)
    all_clear_at = models.DateTimeField(null=True, blank=True)
    # Last silent measurement of an audio_silent incident.
    silent_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["started_at"]
        indexes = [models.Index(fields=["recorder", "started_at"])]

    def __str__(self):
        return f"{self.kind} {self.recorder_id} {self.started_at:%Y-%m-%d %H:%M}"


class AudioSample(models.Model):
    """One successful level measurement; level_db null = no audio track."""

    recorder = models.ForeignKey(
        Recorder, on_delete=models.CASCADE, related_name="audio_samples"
    )
    event = models.ForeignKey(
        "opencast.ScheduledEvent",
        null=True,
        on_delete=models.SET_NULL,
        related_name="audio_samples",
    )
    measured_at = models.DateTimeField()
    level_db = models.FloatField(null=True)

    class Meta:
        ordering = ["measured_at"]
        indexes = [
            models.Index(fields=["event", "measured_at"]),
            models.Index(fields=["measured_at"]),
        ]

    def __str__(self):
        return f"{self.recorder_id} {self.measured_at:%Y-%m-%d %H:%M:%S} {self.level_db}"
