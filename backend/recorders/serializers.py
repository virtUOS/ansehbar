# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from recorders.models import MonitorSettings, Recorder, RecorderStatus


class RecorderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecorderStatus
        fields = [
            "state",
            "live_since",
            "checked_at",
            "agent_state",
            "agent_updated_at",
        ]


class RecorderSerializer(serializers.ModelSerializer):
    status = RecorderStatusSerializer(read_only=True)
    playback_url = serializers.SerializerMethodField()
    current_event = serializers.SerializerMethodField()
    next_event = serializers.SerializerMethodField()
    missing_since = serializers.SerializerMethodField()

    class Meta:
        model = Recorder
        fields = [
            "id",
            "room_name",
            "stream_name",
            "agent_id",
            "active",
            "needs_review",
            "playback_url",
            "status",
            "current_event",
            "next_event",
            "missing_since",
        ]

    def validate_agent_id(self, value):
        # "" (unlinked) is stored as NULL so the unique constraint ignores it.
        return value or None

    def update(self, instance, validated_data):
        old_stream = instance.stream_name
        instance = super().update(instance, validated_data)
        if instance.stream_name != old_stream:
            # The old stream's status says nothing about the new one.
            status, _ = RecorderStatus.objects.get_or_create(recorder=instance)
            status.state = RecorderStatus.UNKNOWN
            status.live_since = None
            status.media_sequence = None
            status.sequence_changed_at = None
            status.save(
                update_fields=[
                    "state",
                    "live_since",
                    "media_sequence",
                    "sequence_changed_at",
                ]
            )
            instance.status = status
        return instance

    def get_playback_url(self, obj) -> str:
        template = self.context.get("url_template")
        if template is None:
            template = MonitorSettings.load().url_template
        return template.format(stream=obj.stream_name)


    def _events(self, obj) -> list:
        return self.context.get("events_by_recorder", {}).get(obj.pk, [])

    def _current(self, obj):
        now = self.context.get("now") or timezone.now()
        # Events are ordered by start, so the first match starts earliest.
        for event in self._events(obj):
            if event.start <= now < event.end:
                return event
        return None

    @staticmethod
    def _event_data(event):
        if event is None:
            return None
        return {
            "title": event.title,
            "series": event.series,
            "start": event.start,
            "end": event.end,
        }

    def get_current_event(self, obj):
        return self._event_data(self._current(obj))

    def get_next_event(self, obj):
        now = self.context.get("now") or timezone.now()
        day_end = self.context.get("day_end")
        for event in self._events(obj):
            if event.start > now and (day_end is None or event.start < day_end):
                return self._event_data(event)
        return None

    def get_missing_since(self, obj):
        if not obj.active or obj.status.state != RecorderStatus.OFFLINE:
            return None
        current = self._current(obj)
        if current is None:
            return None
        now = self.context.get("now") or timezone.now()
        grace = timedelta(minutes=self.context.get("grace_minutes", 0))
        threshold = current.start + grace
        if now < threshold:
            return None
        offline_since = obj.status.offline_since
        since = max(threshold, offline_since) if offline_since else threshold
        return serializers.DateTimeField().to_representation(since)


class MonitorSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitorSettings
        fields = ["url_template", "stale_factor", "missing_grace_minutes"]
