# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from rest_framework import serializers

from recorders.models import MonitorSettings, Recorder, RecorderStatus


class RecorderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecorderStatus
        fields = ["state", "live_since", "checked_at"]


class RecorderSerializer(serializers.ModelSerializer):
    status = RecorderStatusSerializer(read_only=True)
    playback_url = serializers.SerializerMethodField()

    class Meta:
        model = Recorder
        fields = [
            "id",
            "room_name",
            "stream_name",
            "active",
            "needs_review",
            "playback_url",
            "status",
        ]

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


class MonitorSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitorSettings
        fields = ["url_template", "stale_factor"]
