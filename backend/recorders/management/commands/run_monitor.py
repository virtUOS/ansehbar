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
from django.db import close_old_connections, connections
from django.utils import timezone

from opencast.client import OpencastClient, OpencastError
from opencast.models import OpencastSyncState
from opencast.sync import run_opencast_sync
from recorders.models import MonitorSettings, RecorderStatus
from recorders.monitor import run_cycle
from streams.sources import HlsStreamSource

logger = logging.getLogger(__name__)

# Unchanged cycle summaries are logged at INFO at most this often.
SUMMARY_EVERY_SECONDS = 60
# On shutdown, wait at most this long for a running Opencast sync.
SYNC_JOIN_SECONDS = 5


class Command(BaseCommand):
    help = "Probe all active recorders periodically and store their live status."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one cycle, exit.")

    def handle(self, *args, **options):
        self._last_counts = None
        self._last_summary_at = 0.0
        self._last_sync_at = None  # time.monotonic() of the last attempt
        # "pending" until the first (threaded) sync finished; "off" if disabled.
        self._opencast_status = "pending"
        self._insecure_logged = False
        self._sync_thread = None
        self._stop = stop = threading.Event()
        previous = {}
        # Signal handlers only work in the main thread (not under test runners).
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
        interval = settings.MONITOR_INTERVAL_SECONDS
        try:
            # Separate client for Opencast: no redirects followed (credentials
            # must not travel to another host); the OpencastClient adds auth.
            with httpx.Client(follow_redirects=True) as client, httpx.Client() as oc_http:
                if options["once"]:
                    self._sync_opencast(oc_http)
                    self._cycle(client)
                else:
                    try:
                        while True:
                            # The sync runs in its own thread so a slow Opencast
                            # never delays the stream checks.
                            self._start_sync(oc_http)
                            self._cycle(client)
                            if stop.wait(interval):
                                break
                            # Drop stale DB connections between cycles (long-lived process).
                            close_old_connections()
                    finally:
                        stop.set()
                        if self._sync_thread is not None:
                            self._sync_thread.join(SYNC_JOIN_SECONDS)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        logger.info("run_monitor stopped")

    def _sync_due(self):
        """True if Opencast is enabled, safely configured and a sync is due."""
        url = settings.OPENCAST_URL
        if not url:
            self._opencast_status = "off"
            return False
        if url.lower().startswith("http://") and not settings.DEBUG:
            # Basic auth over plain HTTP would expose the credentials.
            if not self._insecure_logged:
                self._insecure_logged = True
                logger.error(
                    "OPENCAST_URL uses plain http://; Opencast sync disabled "
                    "(use https:// or DJANGO_DEBUG=1)"
                )
            self._opencast_status = "error"
            return False
        now = time.monotonic()
        if (
            self._last_sync_at is not None
            and now - self._last_sync_at < settings.OPENCAST_SYNC_SECONDS
            and not self._sync_requested()
        ):
            return False
        self._last_sync_at = now
        return True

    def _sync_requested(self):
        """True if "sync now" was pressed after the last sync attempt."""
        try:
            state = OpencastSyncState.objects.filter(pk=1).first()
            return bool(state and state.sync_requested)
        except Exception:
            logger.exception("could not read the opencast sync request")
            return False

    def _start_sync(self, http_client):
        """Start a sync thread if due; skip while the previous one still runs."""
        if self._sync_thread is not None and self._sync_thread.is_alive():
            logger.debug("opencast sync still running, skipped")
            return
        if not self._sync_due():
            return
        self._sync_thread = threading.Thread(
            target=self._sync_worker, args=(http_client,), name="opencast-sync",
            daemon=True,
        )
        self._sync_thread.start()

    def _sync_worker(self, http_client):
        close_old_connections()
        try:
            self._run_sync(http_client)
        finally:
            # This thread's DB connection is not reused by anyone else.
            connections.close_all()

    def _sync_opencast(self, http_client):
        """Run the Opencast sync inline if enabled and due; never raises."""
        if self._sync_due():
            self._run_sync(http_client)

    def _run_sync(self, http_client):
        """One Opencast sync; never raises."""
        try:
            oc = OpencastClient(
                settings.OPENCAST_URL,
                settings.OPENCAST_USER,
                settings.OPENCAST_PASSWORD,
                http_client,
            )
            run_opencast_sync(oc, timezone.now(), settings.OPENCAST_LOOKAHEAD_DAYS)
            # run_opencast_sync swallows OpencastError and records it in the state.
            error = OpencastSyncState.load().last_error
            self._opencast_status = "error" if error else "ok"
            if error:
                logger.warning("opencast sync failed: %s", error)
        except OpencastError as exc:
            self._opencast_status = "error"
            logger.warning("opencast sync failed: %s", exc)
        except Exception as exc:
            self._opencast_status = "error"
            logger.exception("opencast sync failed unexpectedly")
            try:
                state = OpencastSyncState.load()
                state.last_attempt_at = timezone.now()
                state.last_error = type(exc).__name__[:300]
                state.save(update_fields=["last_attempt_at", "last_error"])
            except Exception:
                logger.exception("could not record opencast sync failure")

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
            self._log_summary(checked, counts, self._opencast_status)
        except Exception:
            # Keep the loop alive across DB or other transient errors.
            logger.exception("monitor cycle failed")

    def _log_summary(self, checked, counts, opencast="off"):
        """INFO when the counts change, otherwise at most once a minute."""
        line = (
            f"monitor cycle: checked={checked} live={counts['live']} "
            f"offline={counts['offline']} unknown={counts['unknown']} opencast={opencast}"
        )
        now = time.monotonic()
        key = (checked, counts, opencast)
        if key != self._last_counts or now - self._last_summary_at >= SUMMARY_EVERY_SECONDS:
            self._last_counts = key
            self._last_summary_at = now
            logger.info(line)
        else:
            logger.debug(line)
