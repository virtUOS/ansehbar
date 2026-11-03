# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import serializers

from recorders.missing import missing_since
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus

# The API reports a level only from a measurement at most this old.
AUDIO_FRESH_SECONDS = 120


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
    next_event_tomorrow = serializers.SerializerMethodField()
    upcoming_today = serializers.SerializerMethodField()
    upcoming_tomorrow = serializers.SerializerMethodField()
    missing_since = serializers.SerializerMethodField()
    last_recording = serializers.SerializerMethodField()
    audio_level_db = serializers.SerializerMethodField()
    silent_since = serializers.SerializerMethodField()

    class Meta:
        model = Recorder
        fields = [
            "id",
            "room_name",
            "stream_name",
            "agent_id",
            "active",
            "needs_review",
            "alarm_mode",
            "playback_url",
            "status",
            "current_event",
            "next_event",
            "next_event_tomorrow",
            "upcoming_today",
            "upcoming_tomorrow",
            "missing_since",
            "last_recording",
            "audio_level_db",
            "silent_since",
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

    def get_next_event_tomorrow(self, obj):
        """First event starting within the next local day (events are ordered
        by start); the view loads them in the same query as today's."""
        day_start = self.context.get("day_end")
        day_end = self.context.get("tomorrow_end")
        if day_start is None or day_end is None:
            return None
        for event in self._events(obj):
            if day_start <= event.start < day_end:
                return self._event_data(event)
        return None

    def get_upcoming_today(self, obj):
        """All events starting later today (local), soonest first."""
        now = self.context.get("now") or timezone.now()
        day_end = self.context.get("day_end")
        if day_end is None:
            return []
        return [
            self._event_data(e)
            for e in self._events(obj)
            if now < e.start < day_end
        ]

    def get_upcoming_tomorrow(self, obj):
        """All events starting within the next local day, soonest first."""
        day_start = self.context.get("day_end")
        day_end = self.context.get("tomorrow_end")
        if day_start is None or day_end is None:
            return []
        return [
            self._event_data(e)
            for e in self._events(obj)
            if day_start <= e.start < day_end
        ]

    def get_last_recording(self, obj):
        """Latest ended event of the lookback window with its problems."""
        event = self.context.get("last_events", {}).get(obj.pk)
        if event is None:
            return None
        now = self.context.get("now") or timezone.now()
        to_iso = serializers.DateTimeField().to_representation
        problems = []
        significant = timedelta(
            minutes=self.context.get(
                "silence_alarm_minutes",
                MonitorSettings._meta.get_field("silence_alarm_minutes").default,
            )
        )
        for incident in self.context.get("incidents_by_event", {}).get(event.pk, []):
            # Only the part within the event counts; an incident still open
            # on an ended event stops at the event end.
            began = max(incident.started_at, event.start)
            ended = min(incident.ended_at or event.end, event.end)
            if ended <= began:
                continue
            # Short silences stay stored (for the timeline), but only those
            # that alerted or reached the alarm time are a problem here.
            if (
                incident.kind == Incident.AUDIO_SILENT
                and incident.alerted_at is None
                and ended - began < significant
            ):
                continue
            seconds = (ended - began).total_seconds()
            problems.append(
                {
                    "kind": incident.kind,
                    "from": to_iso(began),
                    "to": to_iso(ended),
                    "minutes": max(1, round(seconds / 60)),
                }
            )
        status = event.opencast_status
        deadline = event.end + timedelta(minutes=30)
        # "Did not start/finish" only from a status Opencast delivered for this
        # event after the deadline; an older one (or one of an event deleted in
        # Opencast meanwhile) may simply be stale.
        seen_at = event.seen_at
        overdue = now >= deadline and seen_at is not None and seen_at >= deadline
        if status.endswith("PROCESSING_FAILURE"):
            problems.append({"kind": "processing_failed"})
        elif status.endswith("RECORDING_FAILURE"):
            problems.append({"kind": "recording_failed"})
        elif overdue and status.endswith("SCHEDULED"):
            problems.append({"kind": "not_started"})
        elif overdue and status.endswith(("RECORDING", "INGESTING")):
            problems.append({"kind": "not_finished"})
        return {
            "title": event.title,
            "start": to_iso(event.start),
            "end": to_iso(event.end),
            "opencast_status": status,
            "problems": problems,
        }

    def get_audio_level_db(self, obj):
        """Last measured level, only while the measurement is fresh."""
        status = obj.status
        if status.audio_checked_at is None or status.audio_level_db is None:
            return None
        now = self.context.get("now") or timezone.now()
        if now - status.audio_checked_at > timedelta(seconds=AUDIO_FRESH_SECONDS):
            return None
        return status.audio_level_db

    def get_silent_since(self, obj):
        """Start of the open silence incident of the running event."""
        current = self._current(obj)
        if current is None:
            return None
        silence = self.context.get("open_silences", {}).get(obj.pk)
        if silence is None or silence[0] != current.pk:
            return None
        return serializers.DateTimeField().to_representation(silence[1])

    def get_missing_since(self, obj):
        now = self.context.get("now") or timezone.now()
        grace = timedelta(minutes=self.context.get("grace_minutes", 0))
        end_tolerance = timedelta(
            minutes=self.context.get("end_tolerance_minutes", 0)
        )
        since = missing_since(
            obj.active,
            obj.status.state,
            obj.status.offline_since,
            self._current(obj),
            now,
            grace,
            end_tolerance,
        )
        if since is None:
            return None
        return serializers.DateTimeField().to_representation(since)


class MonitorSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitorSettings
        fields = [
            "url_template",
            "stale_factor",
            "missing_grace_minutes",
            "slot_minutes",
            "slot_offset_minutes",
            "ct_minutes",
            "ct_tolerance_minutes",
            "end_tolerance_minutes",
            "alarm_email_enabled",
            "alarm_metrics_enabled",
            "silence_threshold_db",
            "silence_log_minutes",
            "silence_alarm_minutes",
        ]

    def validate(self, attrs):
        minutes = attrs.get("slot_minutes", self.instance and self.instance.slot_minutes)
        offset = attrs.get(
            "slot_offset_minutes", self.instance and self.instance.slot_offset_minutes
        )
        if minutes and offset is not None and offset >= minutes:
            raise serializers.ValidationError(
                {"slot_offset_minutes": _("Must be shorter than the slot length.")}
            )
        log = attrs.get(
            "silence_log_minutes", self.instance and self.instance.silence_log_minutes
        )
        alarm = attrs.get(
            "silence_alarm_minutes", self.instance and self.instance.silence_alarm_minutes
        )
        if log is not None and alarm is not None and alarm < log:
            raise serializers.ValidationError(
                {
                    "silence_alarm_minutes": _(
                        "Must not be shorter than the minimum logged silence."
                    )
                }
            )
        return attrs
