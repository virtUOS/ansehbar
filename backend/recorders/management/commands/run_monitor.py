# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Periodically probe all recorders: `manage.py run_monitor [--once]`."""
import logging
import signal
import threading

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from recorders.models import MonitorSettings, RecorderStatus
from recorders.monitor import run_cycle
from streams.sources import HlsStreamSource

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Probe all active recorders periodically and store their live status."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one cycle, exit.")

    def handle(self, *args, **options):
        stop = threading.Event()
        previous = {}
        # Signal handlers only work in the main thread (not under test runners).
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        interval = settings.MONITOR_INTERVAL_SECONDS
        try:
            with httpx.Client(follow_redirects=True) as client:
                while True:
                    self._cycle(client)
                    if options["once"] or stop.wait(interval):
                        break
                    # Drop stale DB connections between cycles (long-lived process).
                    close_old_connections()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        logger.info("run_monitor stopped")

    def _cycle(self, client):
        try:
            # Reload each cycle so template changes apply without a restart.
            source = HlsStreamSource(MonitorSettings.load().url_template, client)
            checked = run_cycle(source, timezone.now())
            counts = {
                state: RecorderStatus.objects.filter(
                    state=state, recorder__active=True
                ).count()
                for state in (
                    RecorderStatus.LIVE,
                    RecorderStatus.OFFLINE,
                    RecorderStatus.UNKNOWN,
                )
            }
            line = (
                f"monitor cycle: checked={checked} live={counts['live']} "
                f"offline={counts['offline']} unknown={counts['unknown']}"
            )
            logger.info(line)
            self.stdout.write(line)
        except Exception:
            # Keep the loop alive across DB or other transient errors.
            logger.exception("monitor cycle failed")
