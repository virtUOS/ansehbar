# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Measure the audio level of one stream once (for calibrating the threshold).

`manage.py measure_audio <stream> [--seconds N]`
"""
import httpx
from django.core.management.base import BaseCommand

from recorders.models import MonitorSettings
from streams.audio import measure_audio
from streams.sources import HlsStreamSource


class Command(BaseCommand):
    help = "Measure the mean audio level (dBFS) of a stream once."

    def add_arguments(self, parser):
        parser.add_argument("stream")
        parser.add_argument("--seconds", type=int, default=10)

    def handle(self, *args, **options):
        with httpx.Client() as client:
            source = HlsStreamSource(MonitorSettings.load().url_template, client)
            url = source.playback_url(options["stream"])
        result = measure_audio(url, options["seconds"])
        if not result.ok:
            self.stdout.write(f"failed: {result.detail}")
        elif result.level_db is None:
            self.stdout.write("level: no audio track")
        else:
            self.stdout.write(f"level: {result.level_db:.1f} dBFS")
