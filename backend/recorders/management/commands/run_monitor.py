# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Periodically probe all recorders: `manage.py run_monitor [--once]`."""
import logging
import signal
import threading
import time

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from recorders.models import MonitorSettings, RecorderStatus
from recorders.monitor import run_cycle
from streams.sources import HlsStreamSource

logger = logging.getLogger(__name__)

# Unchanged cycle summaries are logged at INFO at most this often.
SUMMARY_EVERY_SECONDS = 60


class Command(BaseCommand):
    help = "Probe all active recorders periodically and store their live status."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one cycle, exit.")

    def handle(self, *args, **options):
        self._last_counts = None
        self._last_summary_at = 0.0
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
            self._log_summary(checked, counts)
        except Exception:
            # Keep the loop alive across DB or other transient errors.
            logger.exception("monitor cycle failed")

    def _log_summary(self, checked, counts):
        """INFO when the counts change, otherwise at most once a minute."""
        line = (
            f"monitor cycle: checked={checked} live={counts['live']} "
            f"offline={counts['offline']} unknown={counts['unknown']}"
        )
        now = time.monotonic()
        key = (checked, counts)
        if key != self._last_counts or now - self._last_summary_at >= SUMMARY_EVERY_SECONDS:
            self._last_counts = key
            self._last_summary_at = now
            logger.info(line)
        else:
            logger.debug(line)
