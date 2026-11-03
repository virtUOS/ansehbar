# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.conf import settings
from django.db import models


class AlarmRecipient(models.Model):
    """An e-mail address that receives stream alarms."""

    email = models.EmailField(unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email


class SentNotification(models.Model):
    """Delivery log; `key` makes delivery idempotent across monitor restarts."""

    EMAIL = "email"
    CHANNEL_CHOICES = [(EMAIL, "e-mail")]
    ALARM = "alarm"
    ALL_CLEAR = "all_clear"
    TEST = "test"
    KIND_CHOICES = [(ALARM, "alarm"), (ALL_CLEAR, "all clear"), (TEST, "test")]

    key = models.CharField(max_length=200, unique=True)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=EMAIL)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    incident = models.ForeignKey(
        "recorders.Incident", null=True, blank=True, on_delete=models.SET_NULL
    )
    recipient = models.EmailField()
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.key
