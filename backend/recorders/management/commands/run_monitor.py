# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Periodically probe all recorders: `manage.py run_monitor [--once]`."""
import logging
import signal
import threading
import time
from functools import partial

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections
from django.utils import timezone

from alarms.delivery import deliver_alarms
from opencast.client import OpencastClient, OpencastError
from opencast.models import OpencastSyncState
from opencast.sync import opencast_sync_enabled, run_opencast_sync
from recorders.audio_monitor import run_audio_pass, update_audio_incidents
from recorders.incidents import update_incidents
from recorders.models import MonitorSettings, RecorderStatus
from recorders.monitor import run_cycle
from recorders.retention import prune_history
from streams.audio import ffmpeg_available, measure_audio
from streams.sources import HlsStreamSource

logger = logging.getLogger(__name__)

# Unchanged cycle summaries are logged at INFO at most this often.
SUMMARY_EVERY_SECONDS = 60
# On shutdown, wait at most this long for a running Opencast sync (and audio pass).
SYNC_JOIN_SECONDS = 5
# Old samples and history are pruned at most this often.
PRUNE_EVERY_SECONDS = 3600


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
        self._audio_thread = None
        self._last_audio_at = None  # time.monotonic() of the last pass start
        self._ffmpeg_ok = None  # checked once, on the first due pass
        self._last_prune_at = None  # time.monotonic() of the last prune
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
                    if self._audio_due():
                        self._run_audio(client)
                    self._prune()
                else:
                    try:
                        while True:
                            # The sync runs in its own thread so a slow Opencast
                            # never delays the stream checks.
                            self._start_sync(oc_http)
                            # Audio measurements take seconds each: own thread too.
                            self._start_audio(client)
                            self._cycle(client)
                            self._prune_if_due()
                            if stop.wait(interval):
                                break
                            # Drop stale DB connections between cycles (long-lived process).
                            close_old_connections()
                    finally:
                        stop.set()
                        if self._sync_thread is not None:
                            self._sync_thread.join(SYNC_JOIN_SECONDS)
                        if self._audio_thread is not None:
                            self._audio_thread.join(SYNC_JOIN_SECONDS)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        logger.info("run_monitor stopped")

    def _sync_due(self):
        """True if Opencast is enabled, safely configured and a sync is due."""
        if not settings.OPENCAST_URL:
            self._opencast_status = "off"
            return False
        if not opencast_sync_enabled():
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
        now = timezone.now()
        try:
            oc = OpencastClient(
                settings.OPENCAST_URL,
                settings.OPENCAST_USER,
                settings.OPENCAST_PASSWORD,
                http_client,
            )
            run_opencast_sync(
                oc, now, settings.OPENCAST_LOOKAHEAD_DAYS, settings.OPENCAST_LOOKBACK_DAYS
            )
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
                # The attempt's start time, like run_opencast_sync records it.
                state.last_attempt_at = now
                state.last_error = type(exc).__name__[:300]
                # Our own failure (e.g. the database), not Opencast's answer.
                state.last_error_kind = "internal"
                state.save(
                    update_fields=["last_attempt_at", "last_error", "last_error_kind"]
                )
            except Exception:
                logger.exception("could not record opencast sync failure")

    def _prune_due(self):
        """True if no prune ran yet or the last one is an hour old."""
        return (
            self._last_prune_at is None
            or time.monotonic() - self._last_prune_at >= PRUNE_EVERY_SECONDS
        )

    def _prune_if_due(self):
        if self._prune_due():
            self._prune()

    def _prune(self):
        """Delete expired samples and history; never raises."""
        self._last_prune_at = time.monotonic()
        try:
            deleted = prune_history(timezone.now())
            if any(deleted.values()):
                logger.info("pruned old data: %s", deleted)
        except Exception:
            logger.exception("pruning old data failed")

    def _audio_available(self):
        """True if audio monitoring is on and ffmpeg exists (checked once)."""
        if not settings.AUDIO_MONITOR_ENABLED:
            return False
        if self._ffmpeg_ok is None:
            self._ffmpeg_ok = ffmpeg_available()
            if not self._ffmpeg_ok:
                logger.error("ffmpeg not found; audio monitoring disabled")
        return self._ffmpeg_ok

    def _audio_due(self):
        """True if audio monitoring is available and a pass is due."""
        if not self._audio_available():
            return False
        now = time.monotonic()
        if (
            self._last_audio_at is not None
            and now - self._last_audio_at < settings.AUDIO_INTERVAL_SECONDS
        ):
            return False
        self._last_audio_at = now
        return True

    def _start_audio(self, http_client):
        """Start an audio pass thread if due; skip while the previous one runs."""
        if self._audio_thread is not None and self._audio_thread.is_alive():
            logger.debug("audio pass still running, skipped")
            return
        if not self._audio_due():
            return
        self._audio_thread = threading.Thread(
            target=self._audio_worker, args=(http_client,), name="audio-monitor",
            daemon=True,
        )
        self._audio_thread.start()

    def _audio_worker(self, http_client):
        close_old_connections()
        try:
            self._run_audio(http_client)
        finally:
            # This thread's DB connection is not reused by anyone else.
            connections.close_all()

    def _run_audio(self, http_client):
        """One audio pass; never raises."""
        try:
            # Reloaded each pass; the pass only uses playback_url, never the client.
            source = HlsStreamSource(MonitorSettings.load().url_template, http_client)
            run_audio_pass(
                partial(measure_audio, seconds=settings.AUDIO_SAMPLE_SECONDS),
                source,
                max_workers=settings.AUDIO_MAX_PARALLEL,
            )
        except Exception:
            logger.exception("audio pass failed")

    def _cycle(self, client):
        try:
            # Reload each cycle so template changes apply without a restart.
            source = HlsStreamSource(MonitorSettings.load().url_template, client)
            now = timezone.now()
            checked = run_cycle(source, now)
            try:
                update_incidents(now)
            except Exception:
                # Incident bookkeeping must never stop the stream cycle.
                logger.exception("updating incidents failed")
            if not self._audio_available():
                # No audio passes: still close audio incidents (event end,
                # stream offline) so no alarm stays raised.
                try:
                    update_audio_incidents(now)
                except Exception:
                    logger.exception("updating audio incidents failed")
            try:
                deliver_alarms(now)
            except Exception:
                # Alarm delivery must never stop the stream cycle either.
                logger.exception("delivering alarms failed")
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
