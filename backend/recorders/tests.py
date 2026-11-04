# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Tests for recorders and monitor settings."""
import json
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now as timezone_now

from alarms.models import SentNotification
from opencast.client import Agent, OpencastError
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from opencast.sync import sync_agents
from recorders import tickets
from recorders.alarm_rules import (
    alarm_due,
    alarm_threshold,
    audio_alarm_due,
    silence_counts_from,
    slot_start,
)
from recorders.models import (
    AudioSample,
    Incident,
    MonitorSettings,
    Recorder,
    RecorderStatus,
)
from recorders.monitor import run_cycle
from recorders.retention import prune_history
from streams.sources import Probe

User = get_user_model()

# Queries of GET /api/recorders/: 6 before stage 3b, plus one for the open
# silences; independent of the row count.
LIST_QUERIES = 7


class RecorderApiTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)

    def test_recorder_alarm_mode(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        url = f"/api/recorders/{rec.pk}/"
        self.assertEqual(self.client.get(url).json()["alarm_mode"], "exact")
        ok = self.client.patch(url, {"alarm_mode": "grid"}, content_type="application/json")
        self.assertEqual(ok.status_code, 200)
        bad = self.client.patch(url, {"alarm_mode": "loud"}, content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_stream_name_keeps_case(self):
        response = self.client.post(
            "/api/recorders/",
            {"room_name": "90/R12", "stream_name": "cap-90-R12"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["stream_name"], "cap-90-R12")
        self.assertTrue(body["playback_url"].endswith("/cap-90-R12/playlist.m3u8"))
        self.assertTrue(Recorder.objects.filter(stream_name="cap-90-R12").exists())

    def test_stream_name_rejects_unsafe(self):
        for name in ["a/b", "..", "a b", "a?x", "a#x", ""]:
            with self.subTest(name=name):
                response = self.client.post(
                    "/api/recorders/",
                    {"room_name": "X", "stream_name": name},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)

    def test_validation_message_follows_accept_language(self):
        def post(lang):
            return self.client.post(
                "/api/recorders/",
                {"room_name": "X", "stream_name": "a/b"},
                content_type="application/json",
                headers={"Accept-Language": lang},
            ).json()["stream_name"][0]

        self.assertTrue(post("de").startswith("Erlaubt sind nur"))
        self.assertTrue(post("en").startswith("Only letters"))

    def test_list_includes_status_and_playback_url(self):
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        rows = self.client.get("/api/recorders/").json()
        self.assertIsInstance(rows, list)
        row = next(r for r in rows if r["stream_name"] == "rec-a")
        self.assertEqual(
            row["playback_url"],
            "https://streaming.example.org/live/rec-a/playlist.m3u8",
        )
        self.assertEqual(
            row["status"],
            {
                "state": "unknown",
                "live_since": None,
                "checked_at": None,
                "agent_state": "",
                "agent_updated_at": None,
            },
        )

    def test_active_filter(self):
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        Recorder.objects.create(room_name="B", stream_name="rec-b", active=False)
        rows = self.client.get("/api/recorders/?active=1").json()
        names = {r["stream_name"] for r in rows}
        self.assertIn("rec-a", names)
        self.assertNotIn("rec-b", names)

    def test_partial_update(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        response = self.client.patch(
            f"/api/recorders/{rec.pk}/", {"active": False},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        self.assertFalse(rec.active)

    def test_changing_stream_name_resets_status(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        live_since = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        RecorderStatus.objects.filter(recorder=rec).update(
            state="live",
            live_since=live_since,
            media_sequence=7,
            sequence_changed_at=live_since,
        )
        response = self.client.patch(
            f"/api/recorders/{rec.pk}/", {"stream_name": "rec-b"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"]["state"], "unknown")
        self.assertIsNone(response.json()["status"]["live_since"])
        status = RecorderStatus.objects.get(recorder=rec)
        self.assertEqual(status.state, "unknown")
        self.assertIsNone(status.live_since)
        self.assertIsNone(status.media_sequence)
        self.assertIsNone(status.sequence_changed_at)

    def test_other_changes_keep_status(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        RecorderStatus.objects.filter(recorder=rec).update(state="live", media_sequence=7)
        response = self.client.patch(
            f"/api/recorders/{rec.pk}/", {"room_name": "B", "stream_name": "rec-a"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        status = RecorderStatus.objects.get(recorder=rec)
        self.assertEqual((status.state, status.media_sequence), ("live", 7))

    def test_list_requires_access(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/api/recorders/").status_code, 403)

    def test_delete_active_recorder_refused(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        response = self.client.delete(f"/api/recorders/{rec.pk}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(), {"detail": "Only deactivated recorders can be deleted."}
        )
        self.assertTrue(Recorder.objects.filter(pk=rec.pk).exists())

    def test_delete_inactive_recorder_cascades(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a", active=False)
        now = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
        ScheduledEvent.objects.create(
            identifier="e1", recorder=rec, start=now, end=now + timedelta(hours=1)
        )
        response = self.client.delete(f"/api/recorders/{rec.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Recorder.objects.filter(pk=rec.pk).exists())
        self.assertFalse(RecorderStatus.objects.filter(recorder_id=rec.pk).exists())
        self.assertFalse(ScheduledEvent.objects.exists())
        self.assertFalse(IgnoredAgent.objects.exists())

    def test_delete_opencast_recorder_ignores_agent(self):
        rec = Recorder.objects.create(
            room_name="A", stream_name="rec-a", agent_id="rec-a", active=False
        )
        self.assertEqual(self.client.delete(f"/api/recorders/{rec.pk}/").status_code, 204)
        ignored = IgnoredAgent.objects.get(agent_id="rec-a")
        self.assertEqual(ignored.created_by, "member")
        result = sync_agents([Agent("rec-a", "idle", None)], datetime.now(timezone.utc))
        self.assertEqual(result.created, 0)
        self.assertFalse(Recorder.objects.exists())
    def test_signal_creates_status(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self.assertEqual(rec.status.state, RecorderStatus.UNKNOWN)


class MonitorSettingsApiTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)

    def put(self, data):
        return self.client.put(
            "/api/settings/monitor/", data, content_type="application/json"
        )

    def test_get_defaults(self):
        body = self.client.get("/api/settings/monitor/").json()
        self.assertEqual(body["stale_factor"], 3)
        self.assertIn("{stream}", body["url_template"])

    def test_alarm_settings_defaults_and_bounds(self):
        body = self.client.get("/api/settings/monitor/").json()
        self.assertEqual(
            [body[k] for k in ["ct_minutes", "ct_tolerance_minutes", "end_tolerance_minutes",
                               "alarm_email_enabled", "alarm_metrics_enabled"]],
            [15, 5, 5, True, True],
        )
        base = {"url_template": body["url_template"], "stale_factor": 3}
        for field, value, code in [("ct_minutes", 61, 400), ("ct_minutes", 0, 200),
                                   ("ct_tolerance_minutes", 31, 400),
                                   ("end_tolerance_minutes", 30, 200)]:
            with self.subTest(field=field, value=value):
                self.assertEqual(self.put({**base, field: value}).status_code, code)

    def test_slot_settings_defaults_and_validation(self):
        body = self.client.get("/api/settings/monitor/").json()
        self.assertEqual((body["slot_minutes"], body["slot_offset_minutes"]), (120, 0))
        base = {"url_template": body["url_template"], "stale_factor": 3}
        for minutes, offset, code in [
            (90, 30, 200), (90, 90, 400), (14, 0, 400), (481, 0, 400), (480, 479, 200),
        ]:
            with self.subTest(minutes=minutes, offset=offset):
                response = self.put(
                    {**base, "slot_minutes": minutes, "slot_offset_minutes": offset}
                )
                self.assertEqual(response.status_code, code, response.content)
        settings_ = MonitorSettings.load()
        self.assertEqual((settings_.slot_minutes, settings_.slot_offset_minutes), (480, 479))
        # Changing only the length still checks it against the stored offset.
        self.assertEqual(self.put({**base, "slot_minutes": 60}).status_code, 400)

    def test_settings_defaults_audio(self):
        body = self.client.get("/api/settings/monitor/").json()
        self.assertEqual(
            [body[k] for k in ["silence_threshold_db", "silence_log_minutes",
                               "silence_alarm_minutes"]],
            [-50, 2, 15],
        )

    def test_settings_alarm_shorter_than_log_rejected(self):
        body = self.client.get("/api/settings/monitor/").json()
        base = {"url_template": body["url_template"], "stale_factor": 3}
        response = self.put(
            {**base, "silence_log_minutes": 10, "silence_alarm_minutes": 5}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["silence_alarm_minutes"],
            ["Must not be shorter than the minimum logged silence."],
        )
        # Partial update is checked against the stored value.
        self.assertEqual(self.put({**base, "silence_log_minutes": 20}).status_code, 400)
        self.assertEqual(
            self.put(
                {**base, "silence_log_minutes": 5, "silence_alarm_minutes": 5}
            ).status_code,
            200,
        )

    def test_health_reports_slots(self):
        settings_ = MonitorSettings.load()
        settings_.slot_minutes = 90
        settings_.slot_offset_minutes = 30
        settings_.save()
        body = self.client.get("/api/monitor/health/").json()
        self.assertEqual(body["slots"], {"minutes": 90, "offset_minutes": 30})

    def test_settings_rejects_template_without_placeholder(self):
        response = self.put(
            {"url_template": "https://example.org/x.m3u8", "stale_factor": 3}
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_two_placeholders(self):
        response = self.put(
            {"url_template": "https://e.org/{stream}/{stream}.m3u8", "stale_factor": 3}
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(DEBUG=False)
    def test_rejects_http_without_debug(self):
        response = self.put({"url_template": "http://e.org/{stream}", "stale_factor": 3})
        self.assertEqual(response.status_code, 400)

    @override_settings(DEBUG=True)
    def test_allows_http_in_debug(self):
        response = self.put({"url_template": "http://e.org/{stream}", "stale_factor": 3})
        self.assertEqual(response.status_code, 200)

    def test_stale_factor_range(self):
        url = "https://e.org/{stream}"
        for factor in (1, 11):
            self.assertEqual(
                self.put({"url_template": url, "stale_factor": factor}).status_code, 400
            )
        self.assertEqual(
            self.put({"url_template": url, "stale_factor": 10}).status_code, 200
        )
        self.assertEqual(MonitorSettings.load().stale_factor, 10)

    @override_settings(OPENCAST_URL="")  # independent of the local .env
    def test_health_reports_opencast_block(self):
        body = self.client.get("/api/monitor/health/").json()
        self.assertEqual(body["opencast"]["enabled"], False)
        self.assertIsNone(body["opencast"]["last_success"])
        ok = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        state = OpencastSyncState.load()
        state.last_success_at = ok
        state.last_error = "secret-looking error"
        state.save()
        with override_settings(
            OPENCAST_URL="https://opencast.example.org", OPENCAST_SYNC_SECONDS=45
        ):
            body = self.client.get("/api/monitor/health/").json()
        block = body["opencast"]
        self.assertEqual(block["enabled"], True)
        self.assertEqual(block["sync_seconds"], 45)
        self.assertEqual(
            datetime.fromisoformat(block["last_success"].replace("Z", "+00:00")), ok
        )
        self.assertEqual(
            set(block),
            {
                "enabled", "insecure_url", "last_success", "sync_seconds",
                "last_attempt", "error_kind", "requested",
            },
        )
        self.assertEqual(block["insecure_url"], False)

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=False)
    def test_health_reports_insecure_opencast_url(self):
        block = self.client.get("/api/monitor/health/").json()["opencast"]
        self.assertEqual(block["enabled"], False)
        self.assertEqual(block["insecure_url"], True)
        with override_settings(OPENCAST_URL=""):
            block = self.client.get("/api/monitor/health/").json()["opencast"]
        self.assertEqual(block["insecure_url"], False)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_health_reports_request_and_error_kind(self):
        t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
        block = self.client.get("/api/monitor/health/").json()["opencast"]
        self.assertIsNone(block["last_attempt"])
        self.assertEqual(block["error_kind"], "")
        self.assertFalse(block["requested"])
        state = OpencastSyncState.load()
        state.last_attempt_at = t1
        state.last_error_kind = "forbidden"
        state.last_error = "/api/agents: forbidden"
        state.save()
        block = self.client.get("/api/monitor/health/").json()["opencast"]
        self.assertEqual(
            datetime.fromisoformat(block["last_attempt"].replace("Z", "+00:00")), t1
        )
        self.assertEqual(block["error_kind"], "forbidden")
        self.assertFalse(block["requested"])
        state.requested_at = t2
        state.save()
        self.assertTrue(self.client.get("/api/monitor/health/").json()["opencast"]["requested"])
        state.last_attempt_at = t2
        state.save()
        self.assertFalse(self.client.get("/api/monitor/health/").json()["opencast"]["requested"])
        state.last_attempt_at = None
        state.save()
        self.assertTrue(self.client.get("/api/monitor/health/").json()["opencast"]["requested"])

    def test_requires_access(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/api/settings/monitor/").status_code, 403)


class MonitorHealthApiTests(TestCase):
    def setUp(self):
        Recorder.objects.all().delete()
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)

    @override_settings(MONITOR_INTERVAL_SECONDS=15)
    def test_reports_latest_check_of_active_recorders(self):
        older = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
        newest = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        a = Recorder.objects.create(room_name="A", stream_name="rec-a")
        b = Recorder.objects.create(room_name="B", stream_name="rec-b")
        c = Recorder.objects.create(room_name="C", stream_name="rec-c", active=False)
        RecorderStatus.objects.filter(recorder=a).update(checked_at=older)
        RecorderStatus.objects.filter(recorder=b).update(checked_at=newest)
        # Inactive recorders are not probed and must not count as a heartbeat.
        RecorderStatus.objects.filter(recorder=c).update(
            checked_at=datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
        body = self.client.get("/api/monitor/health/").json()
        self.assertEqual(
            datetime.fromisoformat(body["last_check"].replace("Z", "+00:00")), newest
        )
        self.assertEqual(body["interval_seconds"], 15)
        self.assertTrue(body["now"])

    def test_last_check_null_without_checks(self):
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        body = self.client.get("/api/monitor/health/").json()
        self.assertIsNone(body["last_check"])

    def test_requires_access(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/api/monitor/health/").status_code, 403)


class FakeSource:
    def __init__(self, probes):
        self.probes = probes
        self.probed = []

    def playback_url(self, stream_name):
        return f"https://example.invalid/{stream_name}"

    def probe(self, stream_name):
        self.probed.append(stream_name)
        result = self.probes[stream_name]
        if isinstance(result, Exception):
            raise result
        return result


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class RunCycleTests(TestCase):
    def setUp(self):
        Recorder.objects.all().delete()

    def test_run_cycle_one_failing_probe_does_not_affect_others(self):
        a = Recorder.objects.create(room_name="A", stream_name="rec-a")
        b = Recorder.objects.create(room_name="B", stream_name="rec-b")
        source = FakeSource(
            {
                "rec-a": RuntimeError("boom"),
                "rec-b": Probe(True, True, 100, 6.0),
            }
        )
        self.assertEqual(run_cycle(source, NOW), 2)
        a.status.refresh_from_db()
        b.status.refresh_from_db()
        self.assertEqual(a.status.state, "unknown")
        self.assertEqual(b.status.state, "live")
        self.assertEqual(b.status.live_since, NOW)
        self.assertEqual(a.status.checked_at, NOW)

    def test_run_cycle_sets_inactive_unknown_and_skips_probe(self):
        r = Recorder.objects.create(room_name="A", stream_name="rec-a", active=False)
        RecorderStatus.objects.filter(recorder=r).update(
            state="live", live_since=NOW, offline_since=NOW
        )
        source = FakeSource({})
        self.assertEqual(run_cycle(source, NOW), 0)
        self.assertEqual(source.probed, [])
        r.status.refresh_from_db()
        self.assertEqual(r.status.state, "unknown")
        self.assertIsNone(r.status.live_since)
        self.assertIsNone(r.status.offline_since)

    def test_run_cycle_keeps_agent_fields_written_during_cycle(self):
        # The Opencast sync (own thread) may commit while the probes run;
        # the cycle must only write the fields it owns.
        r = Recorder.objects.create(room_name="A", stream_name="rec-a")
        RecorderStatus.objects.filter(recorder=r).update(agent_state="idle")
        from recorders import monitor

        real_evaluate = monitor.evaluate

        def evaluate_after_sync(*args, **kwargs):
            RecorderStatus.objects.filter(recorder=r).update(
                agent_state="capturing", agent_updated_at=NOW
            )
            return real_evaluate(*args, **kwargs)

        with mock.patch.object(monitor, "evaluate", evaluate_after_sync):
            run_cycle(FakeSource({"rec-a": Probe(True, True, 100, 6.0)}), NOW)
        r.status.refresh_from_db()
        self.assertEqual(r.status.state, "live")
        self.assertEqual(r.status.checked_at, NOW)
        self.assertEqual(r.status.agent_state, "capturing")
        self.assertEqual(r.status.agent_updated_at, NOW)

    def test_run_cycle_survives_recorder_deleted_during_cycle(self):
        # An admin may delete a recorder while the probes run; the other
        # recorders must still get their status.
        a = Recorder.objects.create(room_name="A", stream_name="rec-a")
        b = Recorder.objects.create(room_name="B", stream_name="rec-b")
        from recorders import monitor

        real_evaluate = monitor.evaluate
        deleted = []

        def evaluate_after_delete(*args, **kwargs):
            if not deleted:
                deleted.append(True)
                Recorder.objects.filter(pk=a.pk).delete()
            return real_evaluate(*args, **kwargs)

        source = FakeSource(
            {"rec-a": Probe(True, True, 1, 6.0), "rec-b": Probe(True, True, 2, 6.0)}
        )
        with mock.patch.object(monitor, "evaluate", evaluate_after_delete):
            self.assertEqual(run_cycle(source, NOW), 2)
        self.assertFalse(Recorder.objects.filter(pk=a.pk).exists())
        b.status.refresh_from_db()
        self.assertEqual(b.status.state, "live")
        self.assertEqual(b.status.checked_at, NOW)

    def test_run_cycle_survives_failing_status_create(self):
        # Creating the missing status of a recorder deleted meanwhile fails
        # (FK); the cycle skips that recorder and goes on.
        a = Recorder.objects.create(room_name="A", stream_name="rec-a")
        b = Recorder.objects.create(room_name="B", stream_name="rec-b", active=False)
        RecorderStatus.objects.filter(recorder=a).delete()
        source = FakeSource({})
        with mock.patch.object(
            RecorderStatus.objects, "create", side_effect=IntegrityError("fk")
        ):
            self.assertEqual(run_cycle(source, NOW), 0)
        self.assertEqual(source.probed, [])
        b.status.refresh_from_db()
        self.assertEqual(b.status.detail, "Recorder inactive")

    def _step(self, recorder, probe, at):
        run_cycle(FakeSource({recorder.stream_name: probe}), at)
        recorder.status.refresh_from_db()

    def test_offline_since_set_on_transition_and_kept(self):
        t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc)
        r = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self._step(r, Probe(True, True, 100, 6.0), t0)
        self.assertIsNone(r.status.offline_since)
        self._step(r, Probe(True, False, None, None, "HTTP 404"), t1)
        self.assertEqual(r.status.state, "offline")
        self.assertEqual(r.status.offline_since, t1)
        self._step(r, Probe(True, False, None, None, "HTTP 404"), t2)
        self.assertEqual(r.status.offline_since, t1)
        self._step(r, Probe(True, True, 200, 6.0), t3)
        self.assertEqual(r.status.state, "live")
        self.assertIsNone(r.status.offline_since)

    def test_offline_since_survives_unknown(self):
        t1 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)
        r = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self._step(r, Probe(True, False, None, None, "HTTP 404"), t1)
        self.assertEqual(r.status.offline_since, t1)
        self._step(r, Probe(False, False, None, None, "timeout"), t2)
        self.assertEqual(r.status.state, "unknown")
        self.assertEqual(r.status.offline_since, t1)
        t3 = datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc)
        self._step(r, Probe(True, False, None, None, "HTTP 404"), t3)
        self.assertEqual(r.status.state, "offline")
        self.assertEqual(r.status.offline_since, t1)

    @override_settings(OPENCAST_URL="")  # independent of the local .env
    def test_run_once_command_exits(self):
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        source = FakeSource({"rec-a": Probe(True, False, None, None, "HTTP 404")})
        with mock.patch(
            "recorders.management.commands.run_monitor.HlsStreamSource",
            return_value=source,
        ):
            call_command("run_monitor", "--once")
        self.assertEqual(Recorder.objects.get().status.state, "offline")


MONITOR = "recorders.management.commands.run_monitor"


class RunMonitorOpencastTests(TestCase):
    def setUp(self):
        Recorder.objects.all().delete()
        self.recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self.source = FakeSource({"rec-a": Probe(True, True, 100, 6.0)})

    def _run(self, sync):
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=self.source), \
                mock.patch(f"{MONITOR}.run_opencast_sync", sync):
            call_command("run_monitor", "--once")

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_run_monitor_syncs_opencast_when_enabled(self):
        order = []
        sync = mock.Mock(side_effect=lambda *a, **k: order.append("sync"))
        self.source.probe = mock.Mock(
            side_effect=lambda n: order.append("probe") or Probe(True, True, 1, 6.0)
        )
        self._run(sync)
        sync.assert_called_once()
        self.assertEqual(order, ["sync", "probe"])
        self.recorder.status.refresh_from_db()
        self.assertIsNotNone(self.recorder.status.checked_at)

    @override_settings(
        OPENCAST_URL="https://opencast.example.org", OPENCAST_PASSWORD="hunter2-pw"
    )
    def test_run_monitor_stream_cycle_survives_sync_error(self):
        sync = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs(MONITOR, level="DEBUG") as logs:
            self._run(sync)
        self.recorder.status.refresh_from_db()
        self.assertIsNotNone(self.recorder.status.checked_at)
        text = "\n".join(
            logs.output + [r.getMessage() for r in logs.records]
        )
        self.assertNotIn("hunter2-pw", text)
        state = OpencastSyncState.load()
        self.assertEqual(state.last_error, "RuntimeError")
        self.assertIsNotNone(state.last_attempt_at)
        self.assertIn("opencast=error", text)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_unexpected_sync_error_records_kind_and_attempt_start(self):
        started = []

        def failing_sync(client, now, lookahead, lookback):
            started.append(now)
            raise RuntimeError("boom")

        state = OpencastSyncState.load()
        state.last_error_kind = ""
        state.save()
        with self.assertLogs(MONITOR, level="DEBUG"):
            self._run(mock.Mock(side_effect=failing_sync))
        state = OpencastSyncState.load()
        self.assertEqual(state.last_error_kind, "internal")
        self.assertEqual(state.last_attempt_at, started[0])

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_run_monitor_logs_opencast_error_without_traceback(self):
        sync = mock.Mock(side_effect=OpencastError("/x: HTTP 500", "server"))
        with self.assertLogs(MONITOR, level="DEBUG") as logs:
            self._run(sync)
        self.assertTrue(any(r.levelname == "WARNING" for r in logs.records))
        self.assertTrue(all(r.exc_info is None for r in logs.records))

    @override_settings(OPENCAST_URL="")
    def test_run_monitor_skips_opencast_when_disabled(self):
        sync = mock.Mock()
        with self.assertLogs(MONITOR, level="DEBUG") as logs:
            self._run(sync)
        sync.assert_not_called()
        self.assertIn("opencast=off", "\n".join(logs.output))
        self.recorder.status.refresh_from_db()
        self.assertIsNotNone(self.recorder.status.checked_at)


    def test_loop_mode_blocking_sync_does_not_delay_cycle(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        sync_started = threading.Event()
        release = threading.Event()
        seen = {}

        def blocking_sync(*args, **kwargs):
            sync_started.set()
            # Inline (blocking) sync would time out here: the cycle never runs.
            seen["released_by_cycle"] = release.wait(5)

        def probe(name):
            seen["sync_started"] = sync_started.wait(2)
            seen["sync_still_running"] = not release.is_set()
            release.set()
            cmd._stop.set()
            return Probe(True, True, 1, 6.0)

        self.source.probe = probe
        state = mock.Mock()
        state.load.return_value.last_error = ""
        state.objects.filter.return_value.first.return_value = None
        with override_settings(OPENCAST_URL="https://opencast.example.org"), \
                mock.patch(f"{MONITOR}.HlsStreamSource", return_value=self.source), \
                mock.patch(f"{MONITOR}.run_opencast_sync", blocking_sync), \
                mock.patch(f"{MONITOR}.OpencastSyncState", state):
            call_command(cmd)
        self.assertEqual(
            seen,
            {"sync_started": True, "sync_still_running": True, "released_by_cycle": True},
        )
        self.recorder.status.refresh_from_db()
        self.assertIsNotNone(self.recorder.status.checked_at)
        self.assertFalse(cmd._sync_thread.is_alive())

    def test_start_sync_skips_while_previous_sync_runs(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        cmd._last_sync_at = None
        cmd._opencast_status = "off"
        cmd._insecure_logged = False
        cmd._sync_thread = mock.Mock(is_alive=mock.Mock(return_value=True))
        with override_settings(OPENCAST_URL="https://opencast.example.org"), \
                mock.patch.object(run_monitor.threading, "Thread") as thread:
            cmd._start_sync(mock.Mock())
        thread.assert_not_called()

    def _bare_cmd(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        cmd._last_sync_at = None
        cmd._opencast_status = "off"
        cmd._insecure_logged = False
        cmd._sync_thread = None
        return cmd

    @override_settings(
        OPENCAST_URL="https://opencast.example.org", OPENCAST_SYNC_SECONDS=3600
    )
    def test_requested_sync_runs_before_interval(self):
        cmd = self._bare_cmd()
        self.assertTrue(cmd._sync_due())  # first sync
        self.assertFalse(cmd._sync_due())  # interval not over
        now = datetime.now(timezone.utc)
        state = OpencastSyncState.load()
        state.last_attempt_at = now
        state.save()
        self.assertFalse(cmd._sync_due())  # no request
        state.requested_at = now - timedelta(seconds=5)
        state.save()
        self.assertFalse(cmd._sync_due())  # request older than the attempt
        state.requested_at = now + timedelta(seconds=5)
        state.save()
        self.assertTrue(cmd._sync_due())  # request newer than the attempt

    @override_settings(
        OPENCAST_URL="https://opencast.example.org", OPENCAST_SYNC_SECONDS=3600
    )
    def test_request_without_any_attempt_is_due(self):
        cmd = self._bare_cmd()
        cmd._last_sync_at = time.monotonic()
        state = OpencastSyncState.load()
        state.requested_at = datetime.now(timezone.utc)
        state.save()
        self.assertTrue(cmd._sync_due())

    @override_settings(OPENCAST_URL="", OPENCAST_SYNC_SECONDS=3600)
    def test_request_without_opencast_is_not_due(self):
        cmd = self._bare_cmd()
        state = OpencastSyncState.load()
        state.requested_at = datetime.now(timezone.utc)
        state.save()
        self.assertFalse(cmd._sync_due())

    @override_settings(
        OPENCAST_URL="https://opencast.example.org", OPENCAST_SYNC_SECONDS=3600
    )
    def test_request_during_running_sync_is_served_after(self):
        cmd = self._bare_cmd()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def fake_sync(client, now, lookahead, lookback):
            calls.append(now)
            state = OpencastSyncState.load()
            state.last_attempt_at = now
            state.save()
            if len(calls) == 1:
                started.set()
                release.wait(5)

        with mock.patch(f"{MONITOR}.run_opencast_sync", fake_sync):
            cmd._start_sync(mock.Mock())
            self.assertTrue(started.wait(2))
            first = cmd._sync_thread
            state = OpencastSyncState.load()
            state.requested_at = datetime.now(timezone.utc)
            state.save()
            cmd._start_sync(mock.Mock())  # still running: no second thread
            self.assertIs(cmd._sync_thread, first)
            self.assertEqual(len(calls), 1)
            release.set()
            first.join(5)
            cmd._start_sync(mock.Mock())  # follow-up for the request
            self.assertIsNot(cmd._sync_thread, first)
            cmd._sync_thread.join(5)
            self.assertEqual(len(calls), 2)
            cmd._start_sync(mock.Mock())  # served: nothing more
            self.assertEqual(len(calls), 2)

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=False)
    def test_run_monitor_refuses_plain_http_without_debug(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        cmd._last_sync_at = None
        cmd._insecure_logged = False
        sync = mock.Mock()
        with mock.patch(f"{MONITOR}.run_opencast_sync", sync), \
                self.assertLogs(MONITOR, level="DEBUG") as logs:
            cmd._sync_opencast(mock.Mock())
            cmd._sync_opencast(mock.Mock())
        sync.assert_not_called()
        self.assertEqual(cmd._opencast_status, "error")
        errors = [r for r in logs.records if r.levelname == "ERROR"]
        self.assertEqual(len(errors), 1)

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=False)
    def test_health_reports_plain_http_without_debug_as_disabled(self):
        self.client.force_login(User.objects.create_user(username="h", is_superuser=True))
        block = self.client.get("/api/monitor/health/").json()["opencast"]
        self.assertFalse(block["enabled"])

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=True)
    def test_run_monitor_allows_plain_http_in_debug(self):
        sync = mock.Mock()
        self._run(sync)
        sync.assert_called_once()


class RunMonitorLoggingTests(TestCase):
    def test_summary_only_on_change_or_once_a_minute(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        cmd._last_counts = None
        cmd._last_summary_at = 0.0
        same = {"live": 1, "offline": 2, "unknown": 0}
        clock = [1000.0]
        logger = "recorders.management.commands.run_monitor"
        with mock.patch.object(run_monitor.time, "monotonic", lambda: clock[0]):
            with self.assertLogs(logger, level="DEBUG") as logs:
                cmd._log_summary(3, dict(same))  # first: INFO
                clock[0] += 10
                cmd._log_summary(3, dict(same))  # unchanged: DEBUG
                clock[0] += 10
                cmd._log_summary(3, {**same, "live": 2})  # changed: INFO
                clock[0] += 61
                cmd._log_summary(3, {**same, "live": 2})  # a minute later: INFO
        levels = [r.levelname for r in logs.records]
        self.assertEqual(levels, ["INFO", "DEBUG", "INFO", "INFO"])


class LoadSiteConfigTests(TestCase):
    TEMPLATE = "https://streams.example.net/{stream}/index.m3u8"

    def run_cmd(self, config, *args, path=None):
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "site.json"
            file.write_text(json.dumps(config) if not isinstance(config, str) else config)
            call_command(
                "load_site_config", "--path", path or str(file), *args, stdout=out
            )
        return out.getvalue()

    def config(self, **extra):
        return {
            "recorders": [
                {"stream_name": "rec-a", "room_name": "A"},
                {"stream_name": "cap-b-R2", "room_name": "B", "active": False},
            ],
            **extra,
        }

    def test_create_update_unchanged(self):
        out = self.run_cmd(self.config())
        self.assertIn("created: 2, updated: 0, unchanged: 0", out)
        self.assertTrue(Recorder.objects.get(stream_name="rec-a").active)
        self.assertFalse(Recorder.objects.get(stream_name="cap-b-R2").active)
        self.assertTrue(RecorderStatus.objects.filter(recorder__stream_name="rec-a").exists())
        # Idempotent.
        self.assertIn("created: 0, updated: 0, unchanged: 2", self.run_cmd(self.config()))
        cfg = self.config()
        cfg["recorders"][0]["room_name"] = "A2"
        self.assertIn("created: 0, updated: 1, unchanged: 1", self.run_cmd(cfg))
        self.assertEqual(Recorder.objects.get(stream_name="rec-a").room_name, "A2")

    def test_stream_name_exact_case(self):
        Recorder.objects.create(room_name="X", stream_name="REC-A")
        self.run_cmd(self.config())
        self.assertEqual(Recorder.objects.count(), 3)

    def test_untouched_unless_deactivate_missing(self):
        Recorder.objects.create(room_name="Z", stream_name="rec-z")
        self.run_cmd(self.config())
        self.assertTrue(Recorder.objects.get(stream_name="rec-z").active)
        out = self.run_cmd(self.config(), "--deactivate-missing")
        self.assertIn("deactivated: 1", out)
        self.assertFalse(Recorder.objects.get(stream_name="rec-z").active)
        self.assertTrue(Recorder.objects.get(stream_name="rec-a").active)

    def test_invalid_file_writes_nothing_and_lists_all_problems(self):
        cfg = {
            "stream_url_template": "ftp://x/{stream}",
            "recorders": [
                {"stream_name": "ok-1", "room_name": "OK"},
                {"stream_name": "bad/name", "room_name": "X"},
                {"stream_name": "ok-1", "room_name": "dup"},
                {"stream_name": "no-room"},
            ],
        }
        with self.assertRaises(CommandError) as ctx:
            self.run_cmd(cfg)
        msg = str(ctx.exception)
        for part in ("stream_url_template", "bad/name", "duplicate", "room_name required"):
            self.assertIn(part, msg)
        self.assertEqual(Recorder.objects.count(), 0)

    def test_invalid_json_and_missing_recorders(self):
        with self.assertRaises(CommandError):
            self.run_cmd("{nope")
        with self.assertRaises(CommandError):
            self.run_cmd({})

    def test_missing_file(self):
        with self.assertRaises(CommandError):
            call_command("load_site_config", "--path", "/nonexistent/x.json")

    def test_default_path_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "s.json"
            file.write_text(json.dumps(self.config()))
            with override_settings(ANSEHBAR_SITE_CONFIG=str(file)):
                call_command("load_site_config", stdout=StringIO())
        self.assertEqual(Recorder.objects.count(), 2)

    def test_stdin_path(self):
        out = StringIO()
        with mock.patch("sys.stdin", StringIO(json.dumps(self.config()))):
            call_command("load_site_config", "--path", "-", stdout=out)
        self.assertEqual(Recorder.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        out = self.run_cmd(self.config(stream_url_template=self.TEMPLATE), "--dry-run")
        self.assertIn("created: 2", out)
        self.assertIn("template changed: yes", out)
        self.assertEqual(Recorder.objects.count(), 0)
        self.assertNotEqual(MonitorSettings.load().url_template, self.TEMPLATE)

    def test_template_update(self):
        out = self.run_cmd(self.config(stream_url_template=self.TEMPLATE))
        self.assertIn("template changed: yes", out)
        self.assertEqual(MonitorSettings.load().url_template, self.TEMPLATE)
        out = self.run_cmd(self.config(stream_url_template=self.TEMPLATE))
        self.assertIn("template changed: no", out)
        # Absent key leaves the template alone.
        self.run_cmd(self.config())
        self.assertEqual(MonitorSettings.load().url_template, self.TEMPLATE)

    def test_load_site_config_accepts_agent_id(self):
        cfg = {
            "recorders": [
                {"stream_name": "rec-a", "room_name": "A", "agent_id": "agent-a"},
                {"stream_name": "rec-b", "room_name": "B"},
            ]
        }
        self.run_cmd(cfg)
        self.assertEqual(Recorder.objects.get(stream_name="rec-a").agent_id, "agent-a")
        self.assertIsNone(Recorder.objects.get(stream_name="rec-b").agent_id)
        cfg["recorders"][1]["agent_id"] = "agent-a"
        with self.assertRaises(CommandError) as ctx:
            self.run_cmd(cfg)
        self.assertIn("duplicate agent_id", str(ctx.exception))

    def test_example_file_loads_cleanly(self):
        example = Path(settings.BASE_DIR) / "site.example.json"
        out = StringIO()
        call_command("load_site_config", "--path", str(example), stdout=out)
        self.assertIn("created: 4", out.getvalue())
        self.assertFalse(Recorder.objects.get(stream_name="rec-20-hall").active)
        self.assertIn("unchanged: 4", self.run_cmd(json.loads(example.read_text())))


BERLIN = ZoneInfo("Europe/Berlin")


def berlin(hour, minute=0, day=10):
    """Local time on 2026-11-<day> (CET, UTC+1)."""
    return datetime(2026, 11, day, hour, minute, tzinfo=BERLIN)


class RecorderEventApiTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)
        self.recorder = Recorder.objects.create(
            room_name="Hall", stream_name="rec-hall", agent_id="rec-hall"
        )
        self.n = 0

    def event(self, start, end, title="T", recorder=None):
        self.n += 1
        return ScheduledEvent.objects.create(
            identifier=f"ev-{self.n}",
            recorder=recorder or self.recorder,
            title=title,
            series="S",
            start=start,
            end=end,
        )

    def get(self, now, recorder=None):
        with mock.patch("django.utils.timezone.now", return_value=now):
            response = self.client.get(f"/api/recorders/{(recorder or self.recorder).pk}/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def set_status(self, state, offline_since=None):
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            state=state, offline_since=offline_since
        )

    def test_current_and_next_event(self):
        first = self.event(berlin(10), berlin(12), "first")
        second = self.event(berlin(14), berlin(16), "second")
        body = self.get(berlin(11))
        self.assertEqual(body["current_event"]["id"], first.pk)
        self.assertEqual(body["next_event"]["id"], second.pk)
        self.assertEqual(body["current_event"]["title"], "first")
        self.assertEqual(body["current_event"]["series"], "S")
        self.assertEqual(body["next_event"]["title"], "second")
        self.assertEqual(
            datetime.fromisoformat(body["next_event"]["start"]), berlin(14)
        )

    def test_no_events_gives_null(self):
        body = self.get(berlin(11))
        self.assertIsNone(body["current_event"])
        self.assertIsNone(body["next_event"])
        self.assertIsNone(body["missing_since"])

    def test_next_event_only_today_local(self):
        self.event(berlin(23, 30), berlin(23, 50), "late")
        self.event(berlin(0, 30, day=11), berlin(1, 0, day=11), "tomorrow")
        body = self.get(berlin(22))
        self.assertEqual(body["next_event"]["title"], "late")
        self.set_status("live")
        ScheduledEvent.objects.filter(title="late").delete()
        self.assertIsNone(self.get(berlin(22))["next_event"])

    def test_next_event_tomorrow_local_day(self):
        self.event(berlin(14, day=3), berlin(15, day=3), "afternoon")
        self.event(berlin(8, day=3), berlin(9, day=3), "morning")
        self.event(berlin(8, day=4), berlin(9, day=4), "day after")
        body = self.get(berlin(20, day=2))
        self.assertIsNone(body["next_event"])
        self.assertEqual(body["next_event_tomorrow"]["title"], "morning")
        self.assertEqual(
            datetime.fromisoformat(body["next_event_tomorrow"]["start"]),
            berlin(8, day=3),
        )

    def test_upcoming_lists_cover_all_events_of_the_day(self):
        self.event(berlin(10, day=2), berlin(12, day=2), "running")
        self.event(berlin(14, day=2), berlin(16, day=2), "today 1")
        self.event(berlin(16, day=2), berlin(18, day=2), "today 2")
        self.event(berlin(8, day=3), berlin(10, day=3), "tomorrow 1")
        self.event(berlin(12, day=3), berlin(14, day=3), "tomorrow 2")
        self.event(berlin(8, day=4), berlin(9, day=4), "day after")
        body = self.get(berlin(11, day=2))
        self.assertEqual(
            [e["title"] for e in body["upcoming_today"]], ["today 1", "today 2"]
        )
        self.assertEqual(
            [e["title"] for e in body["upcoming_tomorrow"]], ["tomorrow 1", "tomorrow 2"]
        )

    def test_next_event_tomorrow_null_without_events(self):
        self.event(berlin(8, day=4), berlin(9, day=4), "day after")
        self.assertIsNone(self.get(berlin(20, day=2))["next_event_tomorrow"])

    def test_next_event_tomorrow_query_count_constant(self):
        def make(count):
            for i in range(count):
                rec = Recorder.objects.create(
                    room_name=f"T{count}-{i}", stream_name=f"t-{count}-{i}"
                )
                self.event(berlin(10, day=3), berlin(12, day=3), recorder=rec)

        def count_queries():
            with mock.patch(
                "django.utils.timezone.now", return_value=berlin(20, day=2)
            ):
                with CaptureQueriesContext(connection) as ctx:
                    response = self.client.get("/api/recorders/")
            self.assertEqual(response.status_code, 200)
            return len(ctx), response.json()

        make(3)
        self.client.get("/api/recorders/")  # warm up: creates the settings row
        small, body = count_queries()
        self.assertEqual(body[1]["next_event_tomorrow"]["title"], "T")
        make(7)
        large, _ = count_queries()
        self.assertEqual(small, large)

    def test_overnight_event_is_current(self):
        self.event(berlin(23), berlin(1, day=11), "night")
        body = self.get(berlin(0, 30, day=11))
        self.assertEqual(body["current_event"]["title"], "night")

    def test_earliest_start_wins_when_overlapping(self):
        self.event(berlin(10, 30), berlin(12), "later")
        self.event(berlin(10), berlin(12), "earlier")
        self.assertEqual(self.get(berlin(11))["current_event"]["title"], "earlier")

    def test_event_end_is_exclusive(self):
        self.event(berlin(10), berlin(12))
        self.assertIsNone(self.get(berlin(12))["current_event"])

    def test_missing_since_after_grace(self):
        self.event(berlin(10), berlin(12))
        self.set_status("offline")
        self.assertIsNone(self.get(berlin(10, 2))["missing_since"])
        body = self.get(berlin(10, 5))
        self.assertEqual(
            datetime.fromisoformat(body["missing_since"]), berlin(10, 3)
        )

    def test_missing_since_uses_offline_since_mid_event(self):
        self.event(berlin(10), berlin(12))
        self.set_status("offline", offline_since=berlin(10, 40))
        body = self.get(berlin(11))
        self.assertEqual(
            datetime.fromisoformat(body["missing_since"]), berlin(10, 40)
        )

    def test_missing_since_respects_grace_setting(self):
        MonitorSettings.objects.update_or_create(
            pk=1, defaults={"missing_grace_minutes": 10}
        )
        self.event(berlin(10), berlin(12))
        self.set_status("offline")
        self.assertIsNone(self.get(berlin(10, 5))["missing_since"])
        self.assertEqual(
            datetime.fromisoformat(self.get(berlin(10, 10))["missing_since"]),
            berlin(10, 10),
        )

    def test_missing_since_respects_end_tolerance_setting(self):
        self.event(berlin(10), berlin(12))
        self.set_status("offline", berlin(11, 56))
        self.assertIsNone(self.get(berlin(11, 58))["missing_since"])
        MonitorSettings.objects.update_or_create(
            pk=1, defaults={"end_tolerance_minutes": 2}
        )
        self.assertEqual(
            datetime.fromisoformat(self.get(berlin(11, 58))["missing_since"]),
            berlin(11, 56),
        )

    def test_unknown_during_event_is_never_missing(self):
        self.event(berlin(10), berlin(12))
        self.set_status("unknown")
        self.assertIsNone(self.get(berlin(11))["missing_since"])

    def test_live_is_never_missing(self):
        self.event(berlin(10), berlin(12))
        self.set_status("live")
        self.assertIsNone(self.get(berlin(11))["missing_since"])

    def test_offline_without_event_is_not_missing(self):
        self.set_status("offline")
        self.assertIsNone(self.get(berlin(11))["missing_since"])

    def test_inactive_recorder_is_never_missing(self):
        self.event(berlin(10), berlin(12))
        self.set_status("offline")
        Recorder.objects.filter(pk=self.recorder.pk).update(active=False)
        self.assertIsNone(self.get(berlin(11))["missing_since"])

    def test_status_exposes_agent_fields(self):
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            agent_state="capturing", agent_updated_at=berlin(9)
        )
        status = self.get(berlin(11))["status"]
        self.assertEqual(status["agent_state"], "capturing")
        self.assertEqual(datetime.fromisoformat(status["agent_updated_at"]), berlin(9))

    def test_agent_id_blank_becomes_null_and_unique_enforced(self):
        def post(stream, agent_id):
            return self.client.post(
                "/api/recorders/",
                {"room_name": "", "stream_name": stream, "agent_id": agent_id},
                content_type="application/json",
            )

        first = post("s-1", "")
        self.assertEqual(first.status_code, 201, first.content)
        self.assertIsNone(first.json()["agent_id"])
        self.assertEqual(first.json()["room_name"], "")
        second = post("s-2", "")
        self.assertEqual(second.status_code, 201, second.content)
        self.assertIsNone(Recorder.objects.get(stream_name="s-2").agent_id)
        dup = post("s-3", "rec-hall")
        self.assertEqual(dup.status_code, 400)
        self.assertIn("agent_id", dup.json())

    def test_agent_id_and_needs_review_writable(self):
        response = self.client.patch(
            f"/api/recorders/{self.recorder.pk}/",
            {"agent_id": "cap-90-R12", "needs_review": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.recorder.refresh_from_db()
        self.assertEqual(self.recorder.agent_id, "cap-90-R12")
        self.assertTrue(self.recorder.needs_review)

    def test_list_query_count_constant(self):
        def make(count):
            for i in range(count):
                rec = Recorder.objects.create(
                    room_name=f"R{count}-{i}", stream_name=f"s-{count}-{i}"
                )
                self.event(berlin(10), berlin(12), recorder=rec)
                self.event(berlin(14), berlin(16), recorder=rec)

        def count_queries():
            with mock.patch("django.utils.timezone.now", return_value=berlin(11)):
                with CaptureQueriesContext(connection) as ctx:
                    response = self.client.get("/api/recorders/")
            self.assertEqual(response.status_code, 200)
            return len(ctx), response.json()

        make(3)
        self.client.get("/api/recorders/")  # warm up: creates the settings row
        small, body = count_queries()
        self.assertEqual(len(body), 4)
        self.assertEqual(body[1]["current_event"]["title"], "T")
        make(7)
        large, body = count_queries()
        self.assertEqual(len(body), 11)
        self.assertEqual(small, large)

    def ended(self, status="", **kw):
        event = self.event(berlin(10, day=9), berlin(12, day=9), **kw)
        ScheduledEvent.objects.filter(pk=event.pk).update(opencast_status=status)
        return event

    def problems(self, now):
        body = self.get(now)
        return body["last_recording"]["problems"]

    def test_last_recording_none(self):
        self.assertIsNone(self.get(berlin(13, day=9))["last_recording"])
        # Running or future events are not "last recording".
        self.event(berlin(10, day=10), berlin(12, day=10))
        self.assertIsNone(self.get(berlin(11, day=10))["last_recording"])

    def test_last_recording_picks_latest_ended(self):
        self.event(berlin(8, day=8), berlin(9, day=8), "older")
        self.event(berlin(10, day=9), berlin(12, day=9), "latest")
        self.event(berlin(14, day=9), berlin(16, day=9), "running")
        body = self.get(berlin(15, day=9))
        last = body["last_recording"]
        self.assertEqual(last["title"], "latest")
        self.assertEqual(datetime.fromisoformat(last["start"]), berlin(10, day=9))
        self.assertEqual(datetime.fromisoformat(last["end"]), berlin(12, day=9))
        self.assertEqual(last["opencast_status"], "")
        self.assertEqual(last["problems"], [])

    def test_last_recording_ignores_events_before_window(self):
        self.event(berlin(10, day=2), berlin(12, day=2), "too old")
        with override_settings(OPENCAST_LOOKBACK_DAYS=7):
            # Window starts 2026-11-03 00:00 local for now on 2026-11-10.
            self.assertIsNone(self.get(berlin(13, day=10))["last_recording"])
        self.event(berlin(10, day=3), berlin(12, day=3), "in window")
        self.assertEqual(
            self.get(berlin(13, day=10))["last_recording"]["title"], "in window"
        )

    def test_last_recording_stream_missing_problems(self):
        event = self.ended()
        other = self.event(berlin(14, day=9), berlin(15, day=9), "other")
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(10, 30, day=9), ended_at=berlin(10, 45, day=9),
        )
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(11, 0, day=9), ended_at=berlin(11, 0, day=9) + timedelta(seconds=10),
        )
        Incident.objects.create(
            recorder=self.recorder, event=other, kind="stream_missing",
            started_at=berlin(14, 10, day=9), ended_at=berlin(14, 20, day=9),
        )
        problems = self.problems(berlin(13, day=9))
        self.assertEqual([p["kind"] for p in problems], ["stream_missing"] * 2)
        self.assertEqual(problems[0]["minutes"], 15)
        self.assertEqual(
            datetime.fromisoformat(problems[0]["from"]), berlin(10, 30, day=9)
        )
        self.assertEqual(
            datetime.fromisoformat(problems[0]["to"]), berlin(10, 45, day=9)
        )
        self.assertEqual(problems[1]["minutes"], 1)

    def test_open_incident_uses_event_end(self):
        event = self.ended()
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(11, 30, day=9), ended_at=None,
        )
        problem = self.problems(berlin(13, day=9))[0]
        self.assertEqual(datetime.fromisoformat(problem["to"]), berlin(12, day=9))
        self.assertEqual(problem["minutes"], 30)

    def test_processing_failure_problem(self):
        self.ended("EVENTS.EVENTS.STATUS.PROCESSING_FAILURE")
        self.assertEqual(
            self.problems(berlin(12, 1, day=9)), [{"kind": "processing_failed"}]
        )

    def test_recording_failure_problem(self):
        self.ended("EVENTS.EVENTS.STATUS.RECORDING_FAILURE")
        self.assertEqual(
            self.problems(berlin(12, 1, day=9)), [{"kind": "recording_failed"}]
        )

    def test_processing_is_not_a_problem(self):
        for status in [
            "EVENTS.EVENTS.STATUS.PROCESSING",
            "EVENTS.EVENTS.STATUS.PROCESSED",
            "",
            "EVENTS.EVENTS.STATUS.SOMETHING_NEW",
        ]:
            with self.subTest(status=status):
                ScheduledEvent.objects.all().delete()
                self.ended(status)
                self.assertEqual(self.problems(berlin(15, day=9)), [])

    def confirmed(self, at):
        """A successful Opencast sync last delivered the events at `at`."""
        ScheduledEvent.objects.update(seen_at=at)

    def test_scheduled_after_end_is_not_started(self):
        self.ended("EVENTS.EVENTS.STATUS.SCHEDULED")
        self.confirmed(berlin(13, day=9))
        self.assertEqual(self.problems(berlin(12, 29, day=9)), [])
        self.assertEqual(
            self.problems(berlin(12, 31, day=9)), [{"kind": "not_started"}]
        )

    def test_recording_after_end_is_not_finished(self):
        for status in ["RECORDING", "INGESTING"]:
            with self.subTest(status=status):
                ScheduledEvent.objects.all().delete()
                self.ended(f"EVENTS.EVENTS.STATUS.{status}")
                self.confirmed(berlin(13, day=9))
                self.assertEqual(self.problems(berlin(12, 29, day=9)), [])
                self.assertEqual(
                    self.problems(berlin(12, 31, day=9)), [{"kind": "not_finished"}]
                )

    def test_not_started_needs_status_confirmed_after_deadline(self):
        self.ended("EVENTS.EVENTS.STATUS.SCHEDULED")  # ends 12:00
        now = berlin(12, 31, day=9)
        # No successful sync at all: the stored status is not confirmed.
        self.assertEqual(self.problems(now), [])
        # Last sync 12:10: before end + 30 min, the status may be stale.
        self.confirmed(berlin(12, 10, day=9))
        self.assertEqual(self.problems(now), [])
        self.confirmed(berlin(12, 31, day=9))
        self.assertEqual(self.problems(now), [{"kind": "not_started"}])

    def test_not_finished_needs_status_confirmed_after_deadline(self):
        self.ended("EVENTS.EVENTS.STATUS.RECORDING")
        self.confirmed(berlin(12, 10, day=9))
        self.assertEqual(self.problems(berlin(12, 31, day=9)), [])
        self.confirmed(berlin(12, 30, day=9))
        self.assertEqual(
            self.problems(berlin(12, 31, day=9)), [{"kind": "not_finished"}]
        )

    def test_event_deleted_in_opencast_is_not_confirmed(self):
        # The sync succeeds after the deadline but no longer delivers the
        # event (deleted in Opencast): its stored status stays unconfirmed.
        self.ended("EVENTS.EVENTS.STATUS.SCHEDULED")
        self.confirmed(berlin(11, day=9))
        OpencastSyncState.objects.update_or_create(
            pk=1, defaults={"last_success_at": berlin(13, day=9)}
        )
        self.assertEqual(self.problems(berlin(13, day=9)), [])

    def test_failure_kinds_do_not_need_confirmation(self):
        self.ended("EVENTS.EVENTS.STATUS.RECORDING_FAILURE")
        self.confirmed(None)
        self.assertEqual(
            self.problems(berlin(12, 1, day=9)), [{"kind": "recording_failed"}]
        )

    def test_incident_interval_clamped_to_event(self):
        event = self.ended()  # 10:00-12:00
        # Started (per offline_since) before the event, ended after it.
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(9, 50, day=9), ended_at=berlin(10, 20, day=9),
        )
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(11, 50, day=9), ended_at=berlin(12, 30, day=9),
        )
        # Entirely outside the event: dropped.
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(9, 0, day=9), ended_at=berlin(9, 30, day=9),
        )
        problems = self.problems(berlin(13, day=9))
        self.assertEqual(len(problems), 2)
        first, second = sorted(problems, key=lambda p: p["from"])
        self.assertEqual(datetime.fromisoformat(first["from"]), berlin(10, day=9))
        self.assertEqual(datetime.fromisoformat(first["to"]), berlin(10, 20, day=9))
        self.assertEqual(first["minutes"], 20)
        self.assertEqual(datetime.fromisoformat(second["from"]), berlin(11, 50, day=9))
        self.assertEqual(datetime.fromisoformat(second["to"]), berlin(12, day=9))
        self.assertEqual(second["minutes"], 10)

    def test_list_query_count_constant_with_last_recording(self):
        def make(count):
            for i in range(count):
                rec = Recorder.objects.create(
                    room_name=f"L{count}-{i}", stream_name=f"l-{count}-{i}"
                )
                event = self.event(berlin(10, day=9), berlin(12, day=9), recorder=rec)
                Incident.objects.create(
                    recorder=rec, event=event, kind="stream_missing",
                    started_at=berlin(11, day=9), ended_at=berlin(11, 5, day=9),
                )

        def count_queries():
            with mock.patch(
                "django.utils.timezone.now", return_value=berlin(13, day=9)
            ):
                with CaptureQueriesContext(connection) as ctx:
                    response = self.client.get("/api/recorders/")
            self.assertEqual(response.status_code, 200)
            return len(ctx), response.json()

        make(3)
        self.client.get("/api/recorders/")  # warm up
        small, body = count_queries()
        self.assertEqual(body[1]["last_recording"]["problems"][0]["minutes"], 5)
        make(7)
        large, _ = count_queries()
        self.assertEqual(small, large)

    def test_audio_level_only_when_fresh(self):
        now = berlin(11)
        self.assertIsNone(self.get(now)["audio_level_db"])
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            audio_level_db=-35.5, audio_checked_at=now - timedelta(seconds=120)
        )
        self.assertEqual(self.get(now)["audio_level_db"], -35.5)
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            audio_checked_at=now - timedelta(seconds=121)
        )
        self.assertIsNone(self.get(now)["audio_level_db"])

    def test_silent_since_only_in_running_event(self):
        past = self.event(berlin(8), berlin(9), "past")
        running = self.event(berlin(10), berlin(12), "running")
        self.set_status("live")
        # Open but on an ended event: not the current silence.
        Incident.objects.create(
            recorder=self.recorder, event=past, kind="audio_silent",
            started_at=berlin(8, 30),
        )
        # A stream gap of the running event is not a silence.
        Incident.objects.create(
            recorder=self.recorder, event=running, kind="stream_missing",
            started_at=berlin(10, 5),
        )
        self.assertIsNone(self.get(berlin(11))["silent_since"])
        # Closed silence of the running event: over.
        Incident.objects.create(
            recorder=self.recorder, event=running, kind="audio_silent",
            started_at=berlin(10, 10), ended_at=berlin(10, 20),
        )
        self.assertIsNone(self.get(berlin(11))["silent_since"])
        Incident.objects.create(
            recorder=self.recorder, event=running, kind="audio_silent",
            started_at=berlin(10, 40),
        )
        body = self.get(berlin(11))
        self.assertEqual(datetime.fromisoformat(body["silent_since"]), berlin(10, 40))
        # After the event, the open incident no longer counts.
        self.assertIsNone(self.get(berlin(12, 5))["silent_since"])

    def test_last_recording_lists_audio_silent(self):
        event = self.ended()  # 10:00-12:00
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="audio_silent",
            started_at=berlin(10, 30, day=9), ended_at=berlin(10, 47, day=9),
        )
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(11, day=9), ended_at=berlin(11, 5, day=9),
        )
        problems = self.problems(berlin(13, day=9))
        self.assertEqual(
            [p["kind"] for p in problems], ["audio_silent", "stream_missing"]
        )
        self.assertEqual(datetime.fromisoformat(problems[0]["from"]), berlin(10, 30, day=9))
        self.assertEqual(datetime.fromisoformat(problems[0]["to"]), berlin(10, 47, day=9))
        self.assertEqual(problems[0]["minutes"], 17)

    def test_last_recording_lists_only_significant_silences(self):
        event = self.ended()  # 10:00-12:00, alarm after 15 minutes (default)
        short = dict(
            recorder=self.recorder, event=event, kind="audio_silent",
            started_at=berlin(10, 10, day=9), ended_at=berlin(10, 13, day=9),
        )
        Incident.objects.create(**short)
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="audio_silent",
            started_at=berlin(10, 30, day=9), ended_at=berlin(10, 50, day=9),
        )
        # Short, but it alerted (e.g. the alarm time was shorter back then).
        Incident.objects.create(
            **{**short, "started_at": berlin(11, 0, day=9),
               "ended_at": berlin(11, 4, day=9), "alerted_at": berlin(11, 3, day=9)}
        )
        # Short stream gaps are listed as before.
        Incident.objects.create(
            recorder=self.recorder, event=event, kind="stream_missing",
            started_at=berlin(11, 30, day=9), ended_at=berlin(11, 31, day=9),
        )
        problems = self.problems(berlin(13, day=9))
        self.assertEqual(
            [(p["kind"], p["minutes"]) for p in problems],
            [("audio_silent", 20), ("audio_silent", 4), ("stream_missing", 1)],
        )
        # The short silence stays stored.
        self.assertEqual(Incident.objects.filter(kind="audio_silent").count(), 3)

    def test_list_query_count_with_silences(self):
        def make(count):
            for i in range(count):
                rec = Recorder.objects.create(
                    room_name=f"Q{count}-{i}", stream_name=f"q-{count}-{i}"
                )
                event = self.event(berlin(10), berlin(12), recorder=rec)
                Incident.objects.create(
                    recorder=rec, event=event, kind="audio_silent",
                    started_at=berlin(10, 30),
                )

        def get_list():
            with mock.patch("django.utils.timezone.now", return_value=berlin(11)):
                response = self.client.get("/api/recorders/")
            self.assertEqual(response.status_code, 200)
            return response.json()

        make(2)
        get_list()  # warm up: creates the settings row
        with self.assertNumQueries(LIST_QUERIES):
            body = get_list()
        self.assertTrue(all(r["silent_since"] for r in body if r["room_name"] != "Hall"))
        make(5)
        with self.assertNumQueries(LIST_QUERIES):
            get_list()

    def test_settings_grace_bounds(self):
        for value, code in [(31, 400), (-1, 400), (30, 200), (0, 200)]:
            with self.subTest(value=value):
                response = self.client.put(
                    "/api/settings/monitor/",
                    {
                        "url_template": MonitorSettings.load().url_template,
                        "stale_factor": 3,
                        "missing_grace_minutes": value,
                    },
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, code, response.content)
        self.assertEqual(
            self.client.get("/api/settings/monitor/").json()["missing_grace_minutes"], 0
        )


class MissingSinceTests(TestCase):
    GRACE = timedelta(minutes=3)
    END_TOL = timedelta(minutes=5)

    def setUp(self):
        recorder = Recorder.objects.create(room_name="M", stream_name="rec-m")
        self.ev = ScheduledEvent.objects.create(
            identifier="ev-m", recorder=recorder, title="T",
            start=berlin(10), end=berlin(12),
        )

    def test_stream_ending_within_end_tolerance_is_not_missing(self):
        from recorders.missing import missing_since

        self.assertIsNone(missing_since(True, "offline", berlin(11, 56), self.ev,
                                        berlin(11, 58), self.GRACE, self.END_TOL))

    def test_stream_ending_before_end_tolerance_is_missing(self):
        from recorders.missing import missing_since

        self.assertEqual(missing_since(True, "offline", berlin(11, 50), self.ev,
                                       berlin(11, 58), self.GRACE, self.END_TOL),
                         berlin(11, 50))

    def test_end_tolerance_defaults_to_zero(self):
        from recorders.missing import missing_since

        self.assertEqual(missing_since(True, "offline", berlin(11, 56), self.ev,
                                       berlin(11, 58), self.GRACE), berlin(11, 56))


class UpdateIncidentsTests(TestCase):
    def setUp(self):
        from recorders.incidents import update_incidents

        self.update = update_incidents
        Recorder.objects.all().delete()
        MonitorSettings.objects.update_or_create(
            pk=1, defaults={"missing_grace_minutes": 3}
        )
        self.recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self.status, _ = RecorderStatus.objects.get_or_create(recorder=self.recorder)
        self.start = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
        self.end = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        self.event = ScheduledEvent.objects.create(
            identifier="ev-1", recorder=self.recorder, title="T",
            start=self.start, end=self.end,
        )

    def at(self, hour, minute):
        return datetime(2026, 11, 2, hour, minute, tzinfo=timezone.utc)

    def set_state(self, state, offline_since=None):
        self.status.state = state
        self.status.offline_since = offline_since
        self.status.save()

    def incidents(self):
        return list(Incident.objects.order_by("started_at", "pk"))

    def test_update_incidents_ignores_audio_incidents(self):
        # Open audio incident, stream live: stays open, not "recovered".
        self.set_state("live")
        audio = Incident.objects.create(
            recorder=self.recorder, event=self.event, kind=Incident.AUDIO_SILENT,
            started_at=self.at(10, 5), silent_until=self.at(10, 9),
        )
        self.update(self.at(10, 10))
        audio.refresh_from_db()
        self.assertIsNone(audio.ended_at)
        self.assertFalse(audio.recovered)
        # A recovered audio incident is not reopened as a stream flicker.
        audio.ended_at, audio.recovered = self.at(10, 10), True
        audio.save()
        self.set_state("offline", self.at(10, 10))
        self.update(self.at(10, 14))
        audio.refresh_from_db()
        self.assertEqual(audio.ended_at, self.at(10, 10))
        self.assertTrue(audio.recovered)
        # Only the genuine stream gap opens a (new) stream incident.
        self.assertEqual(
            [i.kind for i in Incident.objects.exclude(pk=audio.pk)],
            ["stream_missing"],
        )

    def test_incident_opened_after_grace(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 2))
        self.assertEqual(self.incidents(), [])
        self.update(self.at(10, 5))
        (incident,) = self.incidents()
        self.assertEqual(incident.started_at, self.at(10, 3))
        self.assertIsNone(incident.ended_at)
        self.assertEqual(incident.kind, "stream_missing")
        self.assertEqual(incident.event, self.event)
        self.assertEqual(incident.recorder, self.recorder)

    def test_incident_closed_when_live(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.set_state("live")
        self.update(self.at(10, 10))
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.at(10, 10))

    def test_incident_closed_at_event_end(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(11, 59))
        self.assertIsNone(self.incidents()[0].ended_at)
        self.update(self.at(12, 5))
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.end)

    def test_incident_not_duplicated_across_cycles_and_restart(self):
        self.set_state("offline", self.at(9, 50))
        for minute in (5, 6, 7):
            self.update(self.at(10, minute))
        self.assertEqual(len(self.incidents()), 1)

    def test_unknown_keeps_incident_open(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.set_state("unknown", self.at(9, 50))
        self.update(self.at(10, 6))
        self.assertIsNone(self.incidents()[0].ended_at)
        self.set_state("live")
        self.update(self.at(10, 7))
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.at(10, 7))

    def test_second_gap_same_event_new_incident(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.set_state("live")
        self.update(self.at(10, 10))
        self.set_state("offline", self.at(10, 20))
        self.update(self.at(10, 21))
        first, second = self.incidents()
        self.assertEqual(first.ended_at, self.at(10, 10))
        self.assertEqual(second.started_at, self.at(10, 20))
        self.assertIsNone(second.ended_at)

    def at_s(self, hour, minute, second):
        return datetime(2026, 11, 2, hour, minute, second, tzinfo=timezone.utc)

    def recovered_at_10_20(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.set_state("live")
        self.update(self.at(10, 20))

    def test_live_closes_incident_as_recovered(self):
        self.recovered_at_10_20()
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.at(10, 20))
        self.assertTrue(incident.recovered)

    def test_event_end_closes_incident_not_recovered(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.update(self.at(12, 5))
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.end)
        self.assertFalse(incident.recovered)

    def test_flicker_reopens_incident(self):
        self.recovered_at_10_20()
        Incident.objects.update(alerted_at=self.at(10, 6))
        self.set_state("offline", self.at_s(10, 20, 30))
        self.update(self.at_s(10, 20, 40))
        (incident,) = self.incidents()
        self.assertIsNone(incident.ended_at)
        self.assertFalse(incident.recovered)
        self.assertEqual(incident.started_at, self.at(10, 3))
        self.assertEqual(incident.alerted_at, self.at(10, 6))

    def test_flicker_detected_late_reopens_incident(self):
        # Drop 45 s after the return, noticed only 75 s after it.
        self.recovered_at_10_20()
        self.set_state("offline", self.at_s(10, 20, 45))
        self.update(self.at_s(10, 21, 15))
        (incident,) = self.incidents()
        self.assertIsNone(incident.ended_at)
        self.assertFalse(incident.recovered)

    def test_recovered_incident_of_other_event_not_reopened(self):
        event_b = ScheduledEvent.objects.create(
            identifier="ev-2", recorder=self.recorder, title="B",
            start=self.end, end=self.at(14, 0),
        )
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.set_state("live")
        self.update(self.at_s(11, 59, 30))
        self.set_state("offline", self.at(12, 0))
        self.update(self.at_s(12, 3, 10))
        first, second = self.incidents()
        self.assertEqual(first.event, self.event)
        self.assertTrue(first.recovered)
        self.assertEqual(second.event, event_b)
        self.assertEqual(second.started_at, self.at(12, 3))
        self.assertIsNone(second.ended_at)

    def test_drop_after_stable_return_opens_new_incident(self):
        self.recovered_at_10_20()
        self.set_state("offline", self.at_s(10, 21, 30))
        self.update(self.at_s(10, 21, 40))
        first, second = self.incidents()
        self.assertEqual(first.ended_at, self.at(10, 20))
        self.assertTrue(first.recovered)
        self.assertEqual(second.started_at, self.at_s(10, 21, 30))
        self.assertIsNone(second.ended_at)

    def test_stream_ending_within_end_tolerance_opens_no_incident(self):
        self.set_state("offline", self.at(11, 56))
        self.update(self.at(11, 58))
        self.assertEqual(self.incidents(), [])

    def test_inactive_recorder_no_incident(self):
        self.recorder.active = False
        self.recorder.save()
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.assertEqual(self.incidents(), [])

    def test_incident_of_deactivated_recorder_closed_now(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.recorder.active = False
        self.recorder.save()
        self.update(self.at(10, 30))
        (incident,) = self.incidents()
        self.assertEqual(incident.ended_at, self.at(10, 30))
        self.assertFalse(incident.recovered)

    def test_incident_of_deleted_event_closed_now(self):
        self.set_state("offline", self.at(9, 50))
        self.update(self.at(10, 5))
        self.event.delete()
        self.update(self.at(10, 30))
        (incident,) = self.incidents()
        self.assertIsNone(incident.event)
        self.assertEqual(incident.ended_at, self.at(10, 30))
        self.assertFalse(incident.recovered)

    def test_no_incident_without_running_event(self):
        self.set_state("offline", self.at(9, 0))
        self.update(self.at(9, 30))
        self.update(self.at(12, 30))
        self.assertEqual(self.incidents(), [])

    def test_query_count_independent_of_recorder_count(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.update(self.at(10, 5))
            return len(ctx)

        self.set_state("offline", self.at(9, 50))
        base = count()
        for i in range(5):
            r = Recorder.objects.create(room_name=f"B{i}", stream_name=f"rec-b{i}")
            RecorderStatus.objects.update_or_create(
                recorder=r,
                defaults={"state": "offline", "offline_since": self.at(9, 50)},
            )
            ScheduledEvent.objects.create(
                identifier=f"ev-b{i}", recorder=r, start=self.start, end=self.end
            )
        self.assertEqual(count(), base + 0)  # inserts happen in bulk


class RunMonitorIncidentTests(TestCase):
    def test_update_incidents_error_does_not_stop_cycle(self):
        Recorder.objects.all().delete()
        recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        source = FakeSource({"rec-a": Probe(True, True, 100, 6.0)})
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=source), \
                mock.patch(f"{MONITOR}.update_incidents", side_effect=RuntimeError("x")), \
                self.assertLogs(MONITOR, level="ERROR") as logs:
            call_command("run_monitor", "--once")
        recorder.status.refresh_from_db()
        self.assertIsNotNone(recorder.status.checked_at)
        self.assertTrue(any("incidents" in m for m in logs.output))
        self.assertFalse(any("monitor cycle failed" in m for m in logs.output))


class AlarmDueTests(TestCase):
    """Event 10:00-12:00, grace 3, c.t. 15, tolerance 5, slots 120/0."""

    def setUp(self):
        self.s = MonitorSettings(
            missing_grace_minutes=3,
            ct_minutes=15,
            ct_tolerance_minutes=5,
            slot_minutes=120,
            slot_offset_minutes=0,
        )
        self.recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self.ev = self.event(berlin(10), berlin(12))

    def event(self, start, end):
        return ScheduledEvent.objects.create(
            identifier=f"ev-{start:%H%M}-{end:%H%M}",
            recorder=self.recorder,
            start=start,
            end=end,
        )

    def incident(self, started_at, **kwargs):
        kwargs.setdefault("event", self.ev)
        return Incident.objects.create(
            recorder=self.recorder,
            kind=Incident.STREAM_MISSING,
            started_at=started_at,
            **kwargs,
        )

    def test_exact_threshold_is_start_plus_grace(self):
        self.assertEqual(alarm_threshold(self.ev, "exact", self.s), berlin(10, 3))

    def test_grid_threshold_is_ct_plus_tolerance(self):
        self.assertEqual(alarm_threshold(self.ev, "grid", self.s), berlin(10, 20))

    def test_grid_does_not_shift_late_start_further(self):
        ev = self.event(berlin(10, 30), berlin(12))
        self.assertEqual(alarm_threshold(ev, "grid", self.s), berlin(10, 33))

    def test_grid_uses_slot_offset(self):
        self.s.slot_minutes, self.s.slot_offset_minutes = 90, 15
        ev = self.event(berlin(9, 15), berlin(10, 45))
        self.assertEqual(alarm_threshold(ev, "grid", self.s), berlin(9, 35))

    def test_off_threshold_is_none(self):
        self.assertIsNone(alarm_threshold(self.ev, "off", self.s))

    def test_silence_counts_from_exact(self):
        self.assertEqual(silence_counts_from(self.ev, "exact", self.s), berlin(10, 3))

    def test_silence_counts_from_grid_with_ct(self):
        self.assertEqual(silence_counts_from(self.ev, "grid", self.s), berlin(10, 20))

    def test_silence_counts_from_off_uses_exact_threshold(self):
        self.assertEqual(silence_counts_from(self.ev, "off", self.s), berlin(10, 3))

    def test_slot_start_before_offset_is_previous_day(self):
        self.assertEqual(
            slot_start(berlin(0, 5), 90, 15), berlin(22, 45, day=9)
        )

    def test_slot_start_regular(self):
        self.assertEqual(slot_start(berlin(10, 30), 120, 0), berlin(10))
        self.assertEqual(slot_start(berlin(9, 59), 90, 15), berlin(9, 15))

    def test_slot_start_on_dst_day(self):
        # 2026-10-25: clocks go back at 03:00 CEST -> 02:00 CET.
        at = datetime(2026, 10, 25, 10, 30, tzinfo=BERLIN)
        self.assertEqual(
            slot_start(at, 120, 0), datetime(2026, 10, 25, 10, 0, tzinfo=BERLIN)
        )

    def test_mode_off_never_alarms(self):
        self.recorder.alarm_mode = Recorder.ALARM_OFF
        inc = self.incident(berlin(10, 1))
        for now in (berlin(10, 5), berlin(11), berlin(11, 59)):
            self.assertFalse(alarm_due(inc, self.s, now))

    def test_due_only_while_event_runs(self):
        inc = self.incident(berlin(10, 1))
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 2)))
        self.assertTrue(alarm_due(inc, self.s, berlin(10, 4)))
        self.assertFalse(alarm_due(inc, self.s, berlin(12)))
        self.assertFalse(alarm_due(inc, self.s, berlin(9, 59)))

    def test_closed_incident_not_due(self):
        inc = self.incident(berlin(10, 1), ended_at=berlin(10, 2))
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 4)))

    def test_inactive_recorder_not_due(self):
        self.recorder.active = False
        inc = self.incident(berlin(10, 1))
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 4)))

    def test_no_event_not_due(self):
        inc = self.incident(berlin(10, 1), event=None)
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 4)))

    def test_incident_start_after_threshold_delays_alarm(self):
        inc = self.incident(berlin(10, 30))
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 29)))
        self.assertTrue(alarm_due(inc, self.s, berlin(10, 30)))

    def test_grid_mode_waits_for_ct_tolerance(self):
        self.recorder.alarm_mode = Recorder.ALARM_GRID
        inc = self.incident(berlin(10, 1))
        self.assertFalse(alarm_due(inc, self.s, berlin(10, 19)))
        self.assertTrue(alarm_due(inc, self.s, berlin(10, 20)))


class MeasureAudioCommandTests(TestCase):
    def run_command(self, result):
        out = StringIO()
        with mock.patch(
            "recorders.management.commands.measure_audio.measure_audio",
            return_value=result,
        ) as measure:
            call_command("measure_audio", "cap-90-R12", "--seconds", "5", stdout=out)
        return out.getvalue(), measure

    def test_prints_level(self):
        from streams.audio import AudioMeasurement

        text, measure = self.run_command(AudioMeasurement(True, -42.1))
        self.assertIn("level: -42.1 dBFS", text)
        self.assertIn("cap-90-R12", measure.call_args.args[0])
        self.assertEqual(measure.call_args.args[1], 5)

    def test_prints_no_audio_and_failure(self):
        from streams.audio import AudioMeasurement

        text, _ = self.run_command(AudioMeasurement(True, None, "no audio track"))
        self.assertIn("level: no audio track", text)
        text, _ = self.run_command(AudioMeasurement(False, None, "HTTP error 404"))
        self.assertIn("failed: HTTP error 404", text)


def utc(hour, minute, second=0):
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc)


class FakeMeasure:
    """measure(url) -> AudioMeasurement by stream name (last URL segment)."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, url):
        name = url.rsplit("/", 1)[-1]
        self.calls.append(name)
        return self.results[name]


class AudioPassTests(TestCase):
    """Event 10:00-12:00, threshold -50 dBFS, log after 2 minutes."""

    def setUp(self):
        Recorder.objects.all().delete()
        self.recorder = self.make("rec-a")
        self.event = self.make_event(self.recorder, "ev-a", utc(10, 0), utc(12, 0))

    def make(self, stream_name, state=RecorderStatus.LIVE, active=True):
        recorder = Recorder.objects.create(
            room_name=stream_name, stream_name=stream_name, active=active
        )
        RecorderStatus.objects.update_or_create(
            recorder=recorder, defaults={"state": state}
        )
        return recorder

    def make_event(self, recorder, identifier, start, end):
        return ScheduledEvent.objects.create(
            identifier=identifier, recorder=recorder, start=start, end=end
        )

    def run_pass(self, at, results):
        from recorders.audio_monitor import run_audio_pass

        measure = FakeMeasure(results)
        count = run_audio_pass(measure, FakeSource({}), now_fn=lambda: at)
        return count, measure

    def measure_a(self, at, level, ok=True, detail=""):
        from streams.audio import AudioMeasurement

        self.run_pass(at, {"rec-a": AudioMeasurement(ok, level, detail)})
        status = RecorderStatus.objects.get(recorder=self.recorder)
        return status

    def audio_incidents(self):
        return list(Incident.objects.filter(kind=Incident.AUDIO_SILENT).order_by("pk"))

    def test_only_live_with_running_event_measured(self):
        from streams.audio import AudioMeasurement

        no_event = self.make("rec-b")
        offline = self.make("rec-c", state=RecorderStatus.OFFLINE)
        inactive = self.make("rec-d", active=False)
        self.make_event(offline, "ev-c", utc(10, 0), utc(12, 0))
        self.make_event(inactive, "ev-d", utc(10, 0), utc(12, 0))
        self.make_event(no_event, "ev-b", utc(8, 0), utc(10, 0))  # already over
        results = {
            name: AudioMeasurement(True, -20.0)
            for name in ("rec-a", "rec-b", "rec-c", "rec-d")
        }
        count, measure = self.run_pass(utc(10, 30), results)
        self.assertEqual(count, 1)
        self.assertEqual(measure.calls, ["rec-a"])

    def test_silence_starts_and_sound_clears(self):
        status = self.measure_a(utc(10, 10), -60.0)
        self.assertEqual(status.silent_since, utc(10, 10))
        self.assertEqual(status.audio_level_db, -60.0)
        self.assertEqual(status.audio_checked_at, utc(10, 10))
        status = self.measure_a(utc(10, 11), -30.0)
        self.assertIsNone(status.silent_since)
        self.assertEqual(status.audio_level_db, -30.0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.first_audio_at, utc(10, 11))
        self.measure_a(utc(10, 12), -25.0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.first_audio_at, utc(10, 11))

    def test_no_audio_track_is_silent(self):
        status = self.measure_a(utc(10, 10), None, detail="no audio track")
        self.assertEqual(status.silent_since, utc(10, 10))
        self.assertIsNone(status.audio_level_db)
        self.assertEqual(status.audio_detail, "no audio track")

    def test_minus_infinity_is_clamped_and_silent(self):
        from recorders.audio_monitor import AUDIO_FLOOR_DB

        status = self.measure_a(utc(10, 10), float("-inf"))
        self.assertEqual(status.audio_level_db, AUDIO_FLOOR_DB)
        self.assertEqual(status.silent_since, utc(10, 10))

    def test_failed_measurement_keeps_state(self):
        # Silence counts from 10:03 (start + grace): the incident opens at 10:06.
        self.measure_a(utc(10, 0), -60.0)
        self.measure_a(utc(10, 3), -60.0)
        self.measure_a(utc(10, 6), -60.0)
        for minute in range(7, 31):
            status = self.measure_a(utc(10, minute), None, ok=False, detail="timeout")
        self.assertEqual(status.silent_since, utc(10, 0))
        self.assertEqual(status.audio_checked_at, utc(10, 6))
        self.assertEqual(status.audio_level_db, -60.0)
        self.assertEqual(status.audio_detail, "timeout")
        [incident] = self.audio_incidents()
        self.assertIsNone(incident.ended_at)
        self.assertEqual(incident.started_at, utc(10, 3))
        self.assertEqual(incident.silent_until, utc(10, 6))

    def test_incident_opens_after_log_minutes(self):
        self.measure_a(utc(10, 20), -60.0)
        self.measure_a(utc(10, 21), -60.0)
        self.assertEqual(self.audio_incidents(), [])
        self.measure_a(utc(10, 22, 30), -60.0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.started_at, utc(10, 20))
        self.assertEqual(incident.silent_until, utc(10, 22, 30))
        self.assertEqual(incident.event, self.event)
        self.assertIsNone(incident.ended_at)
        self.measure_a(utc(10, 23), -60.0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.silent_until, utc(10, 23))

    def test_incident_recovers_on_sound(self):
        self.measure_a(utc(10, 20), -60.0)
        self.measure_a(utc(10, 25), -60.0)
        self.measure_a(utc(10, 40), -30.0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.ended_at, utc(10, 40))
        self.assertTrue(incident.recovered)
        self.assertEqual(incident.silent_until, utc(10, 25))

    def test_incident_closed_when_stream_drops(self):
        self.measure_a(utc(10, 20), -60.0)
        self.measure_a(utc(10, 25), -60.0)
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            state=RecorderStatus.OFFLINE
        )
        count, measure = self.run_pass(utc(10, 26), {})
        self.assertEqual(count, 0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.ended_at, utc(10, 26))
        self.assertFalse(incident.recovered)
        status = RecorderStatus.objects.get(recorder=self.recorder)
        self.assertIsNone(status.silent_since)
        self.assertIsNone(status.audio_level_db)

    def test_stream_drop_during_pass_is_no_recovery(self):
        from recorders.audio_monitor import run_audio_pass

        self.measure_a(utc(10, 20), -60.0)
        self.measure_a(utc(10, 25), -60.0)
        RecorderStatus.objects.filter(recorder=self.recorder).update(
            state=RecorderStatus.OFFLINE
        )
        calls = []

        def now_fn():
            calls.append(1)
            if len(calls) == 2:
                # The stream cycle wrote live again while the pass measured.
                RecorderStatus.objects.filter(recorder=self.recorder).update(
                    state=RecorderStatus.LIVE
                )
            return utc(10, 26)

        count = run_audio_pass(FakeMeasure({}), FakeSource({}), now_fn=now_fn)
        self.assertEqual(count, 0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.ended_at, utc(10, 26))
        self.assertFalse(incident.recovered)

    def test_silence_across_back_to_back_events(self):
        second = self.make_event(self.recorder, "ev-b", utc(12, 0), utc(14, 0))
        self.measure_a(utc(11, 50), -60.0)
        self.measure_a(utc(11, 53), -60.0)
        [first_incident] = self.audio_incidents()
        self.assertEqual(first_incident.event, self.event)
        self.measure_a(utc(11, 57), -60.0)
        self.measure_a(utc(12, 1), -60.0)
        [first_incident] = self.audio_incidents()
        self.assertEqual(first_incident.ended_at, utc(12, 0))
        self.assertFalse(first_incident.recovered)
        # In the second event silence counts from 12:03 (start + grace).
        self.measure_a(utc(12, 4), -60.0)
        self.assertEqual(len(self.audio_incidents()), 1)
        self.measure_a(utc(12, 5), -60.0)
        first_incident, second_incident = self.audio_incidents()
        self.assertEqual(second_incident.event, second)
        self.assertEqual(second_incident.started_at, utc(12, 3))
        self.assertEqual(second_incident.silent_until, utc(12, 5))

    def test_status_fields_not_clobbered(self):
        from recorders.audio_monitor import run_audio_pass
        from streams.audio import AudioMeasurement

        RecorderStatus.objects.filter(recorder=self.recorder).update(
            media_sequence=100, agent_state="capturing"
        )

        calls = []

        def now_fn():
            calls.append(1)
            if len(calls) == 2:
                # After the measurements: statuses loaded, not yet written.
                RecorderStatus.objects.filter(recorder=self.recorder).update(
                    state=RecorderStatus.OFFLINE, media_sequence=200, agent_state="idle"
                )
            return utc(10, 10)

        run_audio_pass(
            FakeMeasure({"rec-a": AudioMeasurement(True, -60.0)}),
            FakeSource({}),
            now_fn=now_fn,
        )
        status = RecorderStatus.objects.get(recorder=self.recorder)
        self.assertEqual(status.state, RecorderStatus.OFFLINE)
        self.assertEqual(status.media_sequence, 200)
        self.assertEqual(status.agent_state, "idle")
        self.assertEqual(status.audio_level_db, -60.0)

    def test_audio_pass_stores_sample(self):
        from recorders.models import AudioSample

        self.measure_a(utc(10, 10), -35.0)
        sample = AudioSample.objects.get()
        self.assertEqual(sample.recorder, self.recorder)
        self.assertEqual(sample.event, self.event)
        self.assertEqual(sample.measured_at, utc(10, 10))
        self.assertEqual(sample.level_db, -35.0)

    def test_audio_pass_stores_no_track_sample(self):
        from recorders.models import AudioSample

        self.measure_a(utc(10, 10), None)
        self.assertIsNone(AudioSample.objects.get().level_db)

    def test_audio_pass_stores_clamped_sample(self):
        from recorders.audio_monitor import AUDIO_FLOOR_DB
        from recorders.models import AudioSample

        self.measure_a(utc(10, 10), float("-inf"))
        self.assertEqual(AudioSample.objects.get().level_db, AUDIO_FLOOR_DB)

    def test_failed_measurement_stores_no_sample(self):
        from recorders.models import AudioSample

        self.measure_a(utc(10, 10), None, ok=False, detail="boom")
        self.assertEqual(AudioSample.objects.count(), 0)

    def test_measure_exception_is_a_failed_measurement(self):
        from recorders.audio_monitor import run_audio_pass

        def boom(url):
            raise RuntimeError("bad")

        run_audio_pass(boom, FakeSource({}), now_fn=lambda: utc(10, 10))
        status = RecorderStatus.objects.get(recorder=self.recorder)
        self.assertEqual(status.audio_detail, "RuntimeError: bad")
        self.assertIsNone(status.audio_checked_at)
        self.assertIsNone(status.silent_since)

    def set_state(self, state):
        RecorderStatus.objects.filter(recorder=self.recorder).update(state=state)

    def test_unknown_keeps_silence_and_incident(self):
        self.measure_a(utc(10, 20), -60.0)
        status = self.measure_a(utc(10, 23), -60.0)
        [incident] = self.audio_incidents()
        self.set_state(RecorderStatus.UNKNOWN)
        count, measure = self.run_pass(utc(10, 24), {})
        self.assertEqual((count, measure.calls), (0, []))
        status = RecorderStatus.objects.get(recorder=self.recorder)
        self.assertEqual(status.silent_since, utc(10, 20))
        self.assertEqual(status.audio_level_db, -60.0)
        self.assertEqual(status.audio_checked_at, utc(10, 23))
        incident.refresh_from_db()
        self.assertIsNone(incident.ended_at)
        self.assertEqual(incident.silent_until, utc(10, 23))

    def test_unknown_then_live_continues_incident(self):
        self.measure_a(utc(10, 20), -60.0)
        self.measure_a(utc(10, 23), -60.0)
        [incident] = self.audio_incidents()
        self.set_state(RecorderStatus.UNKNOWN)
        self.run_pass(utc(10, 24), {})
        self.run_pass(utc(10, 25), {})
        self.set_state(RecorderStatus.LIVE)
        status = self.measure_a(utc(10, 26), -60.0)
        self.assertEqual(status.silent_since, utc(10, 20))
        [same] = self.audio_incidents()
        self.assertEqual(same.pk, incident.pk)
        self.assertIsNone(same.ended_at)
        self.assertEqual(same.silent_until, utc(10, 26))

    def test_offline_still_resets_silence(self):
        self.measure_a(utc(10, 20), -60.0)
        self.set_state(RecorderStatus.OFFLINE)
        self.run_pass(utc(10, 21), {})
        status = RecorderStatus.objects.get(recorder=self.recorder)
        self.assertIsNone(status.silent_since)

    def test_measurement_gap_restarts_silence(self):
        from recorders.audio_monitor import MAX_MEASUREMENT_GAP

        self.assertEqual(MAX_MEASUREMENT_GAP, timedelta(minutes=5))
        self.measure_a(utc(10, 0), -60.0)
        self.measure_a(utc(10, 3), -60.0)
        self.measure_a(utc(10, 6), -60.0)
        [old] = self.audio_incidents()
        for minute in range(7, 31):
            self.measure_a(utc(10, minute), None, ok=False, detail="timeout")
        status = self.measure_a(utc(10, 31), -60.0)
        self.assertEqual(status.silent_since, utc(10, 31))
        old.refresh_from_db()
        self.assertEqual(old.ended_at, utc(10, 6))
        self.assertFalse(old.recovered)
        settings_ = MonitorSettings.load()
        open_incidents = Incident.objects.filter(
            kind=Incident.AUDIO_SILENT, ended_at__isnull=True
        ).select_related("recorder", "event")
        self.assertFalse(
            any(audio_alarm_due(i, settings_, utc(10, 31), set()) for i in open_incidents)
        )
        # A fresh incident starts from the new silence after the log time.
        self.measure_a(utc(10, 33), -60.0)
        _, new = self.audio_incidents()
        self.assertEqual(new.started_at, utc(10, 31))

    def test_gaps_below_limit_keep_extending(self):
        self.measure_a(utc(10, 10), -60.0)
        for minute in (14, 18, 22, 26):
            self.measure_a(utc(10, minute) - timedelta(seconds=1), None, ok=False)
            status = self.measure_a(utc(10, minute), -60.0)
        self.assertEqual(status.silent_since, utc(10, 10))
        [incident] = self.audio_incidents()
        self.assertEqual(incident.started_at, utc(10, 10))
        self.assertEqual(incident.silent_until, utc(10, 26))

    def test_silence_counts_from_grid_threshold(self):
        settings_ = MonitorSettings.load()
        # Slots start every local hour, so 10:00 UTC (11:00 local) starts one.
        settings_.slot_minutes, settings_.slot_offset_minutes = 60, 0
        settings_.ct_minutes, settings_.ct_tolerance_minutes = 15, 5
        settings_.save()
        self.recorder.alarm_mode = Recorder.ALARM_GRID
        self.recorder.save()
        for minute in range(0, 22):
            self.measure_a(utc(10, minute), -60.0)
        self.assertEqual(self.audio_incidents(), [])
        self.measure_a(utc(10, 22), -60.0)
        [incident] = self.audio_incidents()
        self.assertEqual(incident.started_at, utc(10, 20))
        for minute in range(23, 36):
            self.measure_a(utc(10, minute), -60.0)
            incident.refresh_from_db()
            due = audio_alarm_due(
                Incident.objects.select_related("recorder", "event").get(pk=incident.pk),
                settings_, utc(10, minute), set(),
            )
            self.assertEqual(due, minute >= 35, minute)


class RunMonitorAudioTests(TestCase):
    def _bare_cmd(self):
        from recorders.management.commands import run_monitor

        cmd = run_monitor.Command()
        cmd._audio_thread = None
        cmd._last_audio_at = None
        cmd._ffmpeg_ok = None
        return cmd

    @override_settings(AUDIO_MONITOR_ENABLED=True, AUDIO_INTERVAL_SECONDS=30)
    def test_pass_skipped_while_previous_runs(self):
        from recorders.management.commands import run_monitor

        cmd = self._bare_cmd()
        clock = [1000.0]
        with mock.patch.object(run_monitor.time, "monotonic", lambda: clock[0]), \
                mock.patch(f"{MONITOR}.ffmpeg_available", return_value=True), \
                mock.patch.object(run_monitor.threading, "Thread") as thread:
            thread.return_value.is_alive.return_value = True
            cmd._start_audio(mock.Mock())
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(thread.call_args.kwargs["name"], "audio-monitor")
            clock[0] += 60  # interval over, but the first pass still runs
            cmd._start_audio(mock.Mock())
            self.assertEqual(thread.call_count, 1)
            thread.return_value.is_alive.return_value = False
            cmd._start_audio(mock.Mock())  # 60 s since the last start: due
            self.assertEqual(thread.call_count, 2)
            clock[0] += 29  # finished, but the interval is not over
            cmd._start_audio(mock.Mock())
            self.assertEqual(thread.call_count, 2)
            clock[0] += 1
            cmd._start_audio(mock.Mock())
            self.assertEqual(thread.call_count, 3)

    @override_settings(AUDIO_MONITOR_ENABLED=False)
    def test_disabled_never_starts(self):
        from recorders.management.commands import run_monitor

        cmd = self._bare_cmd()
        with mock.patch.object(run_monitor.threading, "Thread") as thread:
            cmd._start_audio(mock.Mock())
        thread.assert_not_called()

    @override_settings(AUDIO_MONITOR_ENABLED=True)
    def test_missing_ffmpeg_logged_once(self):
        from recorders.management.commands import run_monitor

        cmd = self._bare_cmd()
        with mock.patch(f"{MONITOR}.ffmpeg_available", return_value=False), \
                mock.patch.object(run_monitor.threading, "Thread") as thread, \
                self.assertLogs(MONITOR, level="ERROR") as logs:
            cmd._start_audio(mock.Mock())
            cmd._last_audio_at = None
            cmd._start_audio(mock.Mock())
        thread.assert_not_called()
        self.assertEqual(
            logs.output, [f"ERROR:{MONITOR}:ffmpeg not found; audio monitoring disabled"]
        )

    def _cycle_with_audio_off(self):
        Recorder.objects.all().delete()
        recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        event = ScheduledEvent.objects.create(
            identifier="ev-a", recorder=recorder, start=utc(10, 0), end=utc(12, 0)
        )
        incident = Incident.objects.create(
            recorder=recorder, event=event, kind=Incident.AUDIO_SILENT,
            started_at=utc(10, 10), silent_until=utc(10, 30), alerted_at=utc(10, 25),
        )
        source = FakeSource({"rec-a": Probe(True, True, 100, 6.0)})
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=source), \
                mock.patch(f"{MONITOR}.timezone.now", return_value=utc(12, 1)), \
                mock.patch(f"{MONITOR}.ffmpeg_available", return_value=False), \
                mock.patch(f"{MONITOR}.run_audio_pass") as audio, \
                self.assertLogs(MONITOR, level="INFO"):
            call_command("run_monitor", "--once")
        audio.assert_not_called()
        incident.refresh_from_db()
        return incident

    @override_settings(OPENCAST_URL="", AUDIO_MONITOR_ENABLED=False)
    def test_disabled_audio_still_closes_incidents(self):
        incident = self._cycle_with_audio_off()
        self.assertEqual(incident.ended_at, utc(12, 0))

    @override_settings(OPENCAST_URL="", AUDIO_MONITOR_ENABLED=True)
    def test_missing_ffmpeg_still_closes_incidents(self):
        incident = self._cycle_with_audio_off()
        self.assertEqual(incident.ended_at, utc(12, 0))

    @override_settings(OPENCAST_URL="", AUDIO_MONITOR_ENABLED=True)
    def test_once_runs_audio_pass_inline(self):
        Recorder.objects.all().delete()
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        source = FakeSource({"rec-a": Probe(True, True, 100, 6.0)})
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=source), \
                mock.patch(f"{MONITOR}.ffmpeg_available", return_value=True), \
                mock.patch(f"{MONITOR}.run_audio_pass", return_value=0) as audio:
            call_command("run_monitor", "--once")
        audio.assert_called_once()


class AudioSettingsTests(TestCase):
    def test_parallel_and_sample_seconds_at_least_one(self):
        import importlib

        import config.settings as module

        self.addCleanup(importlib.reload, module)
        env = {"AUDIO_MAX_PARALLEL": "0", "AUDIO_SAMPLE_SECONDS": "-5"}
        with mock.patch.dict("os.environ", env):
            importlib.reload(module)
        self.assertEqual(module.AUDIO_MAX_PARALLEL, 1)
        self.assertEqual(module.AUDIO_SAMPLE_SECONDS, 1)


class AudioAlarmDueTests(TestCase):
    """Event 10:00-12:00 local, alarm after 15 minutes of silence."""

    def setUp(self):
        self.s = MonitorSettings(silence_alarm_minutes=15)
        self.recorder = Recorder.objects.create(room_name="A", stream_name="rec-a")
        self.ev = ScheduledEvent.objects.create(
            identifier="ev-audio", recorder=self.recorder,
            start=berlin(10), end=berlin(12),
        )
        self.now = berlin(10, 30)

    def incident(self, silent_until=berlin(10, 15), **kwargs):
        kwargs.setdefault("event", self.ev)
        return Incident.objects.create(
            recorder=self.recorder, kind=Incident.AUDIO_SILENT,
            started_at=berlin(10), silent_until=silent_until, **kwargs,
        )

    def due(self, incident, alerted=frozenset(), now=None):
        return audio_alarm_due(incident, self.s, now or self.now, set(alerted))

    def test_due_at_exactly_alarm_minutes(self):
        self.assertTrue(self.due(self.incident(berlin(10, 15))))

    def test_not_due_just_below(self):
        incident = self.incident(berlin(10, 14) + timedelta(seconds=59))
        self.assertFalse(self.due(incident))

    def test_off_mode_never_alarms(self):
        self.recorder.alarm_mode = Recorder.ALARM_OFF
        self.recorder.save()
        self.assertFalse(self.due(self.incident(self.ev.start + timedelta(hours=1))))

    def test_inactive_recorder_never_alarms(self):
        self.recorder.active = False
        self.recorder.save()
        self.assertFalse(self.due(self.incident()))

    def test_event_already_alerted(self):
        self.assertFalse(self.due(self.incident(), alerted={self.ev.pk}))

    def test_other_event_alerted_does_not_matter(self):
        self.assertTrue(self.due(self.incident(), alerted={self.ev.pk + 1}))

    def test_without_silent_until(self):
        self.assertFalse(self.due(self.incident(silent_until=None)))

    def test_closed_incident_or_ended_event(self):
        self.assertFalse(self.due(self.incident(ended_at=berlin(10, 20))))
        self.assertFalse(self.due(self.incident(), now=berlin(12, 1)))
        self.assertFalse(self.due(self.incident(event=None)))

    def test_failed_measurements_do_not_extend_silence(self):
        # Silent since 10:00, last silent measurement 10:03, failures until 10:30.
        incident = self.incident(silent_until=berlin(10, 3))
        self.assertFalse(self.due(incident, now=berlin(10, 30)))


class RetentionTests(TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        self.recorder = Recorder.objects.create(room_name="Hall", stream_name="rec-hall")

    def sample(self, days):
        return AudioSample.objects.create(
            recorder=self.recorder,
            measured_at=self.now - timedelta(days=days),
            level_db=-30,
        )

    def event(self, ident, end_days_ago, hours=1):
        end = self.now - timedelta(days=end_days_ago)
        return ScheduledEvent.objects.create(
            identifier=ident, recorder=self.recorder, title="T",
            start=end - timedelta(hours=hours), end=end,
        )

    def incident(self, event, started):
        return Incident.objects.create(
            recorder=self.recorder, event=event, kind=Incident.STREAM_MISSING,
            started_at=started,
        )

    def test_prune_deletes_old_samples_only(self):
        old, recent = self.sample(31), self.sample(29)
        result = prune_history(self.now)
        self.assertEqual(result["samples"], 1)
        self.assertEqual(list(AudioSample.objects.all()), [recent])
        self.assertFalse(AudioSample.objects.filter(pk=old.pk).exists())

    def test_prune_deletes_event_with_incidents(self):
        event = self.event("old", 401)
        first = self.incident(event, event.start)
        self.incident(event, event.start + timedelta(minutes=20))
        note = SentNotification.objects.create(
            key="k1", kind=SentNotification.ALARM, incident=first, recipient="a@example.org"
        )
        SentNotification.objects.filter(pk=note.pk).update(
            created_at=self.now - timedelta(days=401)
        )
        result = prune_history(self.now)
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["incidents"], 2)
        self.assertEqual(result["notifications"], 1)
        self.assertFalse(ScheduledEvent.objects.exists())
        self.assertFalse(Incident.objects.exists())
        self.assertFalse(SentNotification.objects.exists())

    def test_prune_keeps_event_ending_after_cutoff(self):
        event = self.event("edge", 399)
        event.start = self.now - timedelta(days=400, hours=1)
        event.save()
        incident = self.incident(event, event.start + timedelta(minutes=5))
        prune_history(self.now)
        self.assertTrue(ScheduledEvent.objects.filter(pk=event.pk).exists())
        incident.refresh_from_db()
        self.assertEqual(incident.event_id, event.pk)

    def test_prune_uses_settings(self):
        MonitorSettings.objects.update_or_create(pk=1, defaults={"sample_retention_days": 1})
        self.sample(2)
        self.assertEqual(prune_history(self.now)["samples"], 1)

    def test_settings_retention_bounds(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)
        body = self.client.get("/api/settings/monitor/").json()
        self.assertEqual(
            (body["sample_retention_days"], body["history_retention_days"]), (30, 400)
        )
        for field, value, code in [("history_retention_days", 182, 400),
                                   ("history_retention_days", 183, 200),
                                   ("sample_retention_days", 0, 400),
                                   ("sample_retention_days", 365, 200)]:
            with self.subTest(field=field, value=value):
                response = self.client.put(
                    "/api/settings/monitor/", {**body, field: value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, code)

    @override_settings(OPENCAST_URL="")
    def test_run_monitor_once_prunes(self):
        source = FakeSource({"rec-hall": Probe(True, True, 100, 6.0)})
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=source), \
                mock.patch(f"{MONITOR}.prune_history", return_value={}) as prune:
            call_command("run_monitor", "--once")
        prune.assert_called_once()

    @override_settings(OPENCAST_URL="")
    def test_prune_failure_does_not_stop_monitor(self):
        source = FakeSource({"rec-hall": Probe(True, True, 100, 6.0)})
        with mock.patch(f"{MONITOR}.HlsStreamSource", return_value=source), \
                mock.patch(f"{MONITOR}.prune_history", side_effect=RuntimeError("x")), \
                self.assertLogs(MONITOR, "ERROR"):
            call_command("run_monitor", "--once")


class RoomCalendarApiTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)
        self.recorder = Recorder.objects.create(
            room_name="Testraum 1", stream_name="cap-test-1"
        )
        self.n = 0

    def event(self, start, end, title="T", recorder=None, **extra):
        self.n += 1
        return ScheduledEvent.objects.create(
            identifier=f"cal-{self.n}",
            recorder=recorder or self.recorder,
            title=title,
            series="S",
            start=start,
            end=end,
            **extra,
        )

    def incident(self, event, started, ended, kind="stream_missing"):
        return Incident.objects.create(
            recorder=event.recorder, event=event, kind=kind,
            started_at=started, ended_at=ended,
        )

    def get(self, query="", recorder=None, now=None):
        url = f"/api/recorders/{(recorder or self.recorder).pk}/calendar/{query}"
        if now is None:
            return self.client.get(url)
        with mock.patch("django.utils.timezone.now", return_value=now):
            return self.client.get(url)

    def test_calendar_week_lists_events_with_incidents(self):
        late = self.event(berlin(14, day=11), berlin(15, day=11), "late")
        early = self.event(berlin(10, day=10), berlin(11, day=10), "early",
                           first_audio_at=berlin(10, 5, day=10))
        self.incident(early, berlin(10, 20, day=10), berlin(10, 30, day=10))
        self.incident(late, berlin(14, 10, day=11), berlin(14, 20, day=11))
        response = self.get("?from=2026-11-09", now=berlin(12, day=12))
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(
            datetime.fromisoformat(body["from"]), datetime(2026, 11, 9, tzinfo=BERLIN)
        )
        self.assertEqual(
            datetime.fromisoformat(body["to"]), datetime(2026, 11, 16, tzinfo=BERLIN)
        )
        self.assertEqual(
            body["recorders"],
            [{"id": self.recorder.pk, "room_name": "Testraum 1",
              "stream_name": "cap-test-1", "active": True}],
        )
        self.assertEqual([e["title"] for e in body["events"]], ["early", "late"])
        first = body["events"][0]
        self.assertEqual(first["id"], early.pk)
        self.assertEqual(first["recorder_id"], self.recorder.pk)
        self.assertEqual(first["series"], "S")
        self.assertEqual(
            datetime.fromisoformat(first["first_audio_at"]), berlin(10, 5, day=10)
        )
        self.assertIsNone(body["events"][1]["first_audio_at"])
        self.assertEqual(len(first["incidents"]), 1)
        incident = first["incidents"][0]
        self.assertEqual(
            set(incident),
            {"id", "kind", "started_at", "ended_at", "recovered", "alerted_at",
             "all_clear_at", "silent_until"},
        )
        self.assertEqual(incident["kind"], "stream_missing")
        self.assertIsNone(incident["alerted_at"])
        self.assertEqual(first["problems"][0]["kind"], "stream_missing")
        self.assertEqual(first["problems"][0]["minutes"], 10)

    def test_calendar_week_across_dst(self):
        # DST ends on Sunday 2026-10-25 (CEST -> CET).
        sunday = self.event(
            datetime(2026, 10, 25, 21, tzinfo=BERLIN),
            datetime(2026, 10, 25, 22, tzinfo=BERLIN), "sunday",
        )
        self.event(
            datetime(2026, 10, 26, 0, 30, tzinfo=BERLIN),
            datetime(2026, 10, 26, 1, 30, tzinfo=BERLIN), "monday",
        )
        body = self.get("?from=2026-10-19&days=7").json()
        self.assertEqual([e["id"] for e in body["events"]], [sunday.pk])
        self.assertEqual(
            datetime.fromisoformat(body["to"]).astimezone(timezone.utc)
            - datetime.fromisoformat(body["from"]).astimezone(timezone.utc),
            timedelta(days=7, hours=1),
        )

    def test_calendar_includes_same_room_recorders(self):
        old = Recorder.objects.create(
            room_name="Testraum 1", stream_name="cap-test-old", active=False
        )
        other = Recorder.objects.create(room_name="Testraum 2", stream_name="cap-test-2")
        mine = self.event(berlin(10), berlin(11), "new")
        theirs = self.event(berlin(12), berlin(13), "old", recorder=old)
        self.event(berlin(14), berlin(15), "elsewhere", recorder=other)
        for rec in (self.recorder, old):
            body = self.get("?from=2026-11-10", recorder=rec).json()
            self.assertEqual({e["id"] for e in body["events"]}, {mine.pk, theirs.pk})
            self.assertEqual(
                {r["id"] for r in body["recorders"]}, {self.recorder.pk, old.pk}
            )
            by_id = {e["id"]: e for e in body["events"]}
            self.assertEqual(by_id[theirs.pk]["recorder_id"], old.pk)
            self.assertEqual(
                [r["active"] for r in body["recorders"] if r["id"] == old.pk], [False]
            )

    def test_calendar_empty_room_name_stays_alone(self):
        a = Recorder.objects.create(room_name="", stream_name="cap-test-a")
        b = Recorder.objects.create(room_name="", stream_name="cap-test-b")
        ea = self.event(berlin(10), berlin(11), "a", recorder=a)
        eb = self.event(berlin(12), berlin(13), "b", recorder=b)
        body = self.get("?from=2026-11-10", recorder=a).json()
        self.assertEqual([e["id"] for e in body["events"]], [ea.pk])
        self.assertEqual([r["id"] for r in body["recorders"]], [a.pk])
        body = self.get("?from=2026-11-10", recorder=b).json()
        self.assertEqual([e["id"] for e in body["events"]], [eb.pk])

    def test_calendar_rejects_bad_params(self):
        for query in ["?from=2026-13-01", "?from=abc", "?days=0", "?days=8",
                      "?days=x", "?days="]:
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()["detail"])
        missing = self.client.get("/api/recorders/999999/calendar/")
        self.assertEqual(missing.status_code, 404)

    def test_calendar_defaults_to_today_and_seven_days(self):
        body = self.get(now=berlin(12, day=10)).json()
        self.assertEqual(
            datetime.fromisoformat(body["from"]), datetime(2026, 11, 10, tzinfo=BERLIN)
        )
        self.assertEqual(
            datetime.fromisoformat(body["to"]), datetime(2026, 11, 17, tzinfo=BERLIN)
        )

    def test_calendar_overlap(self):
        crossing = self.event(
            datetime(2026, 11, 9, 23, tzinfo=BERLIN),
            datetime(2026, 11, 10, 1, tzinfo=BERLIN), "crossing",
        )
        self.event(  # ends exactly at from
            datetime(2026, 11, 9, 22, tzinfo=BERLIN),
            datetime(2026, 11, 10, 0, tzinfo=BERLIN), "before",
        )
        self.event(  # starts exactly at to
            datetime(2026, 11, 11, 0, tzinfo=BERLIN),
            datetime(2026, 11, 11, 1, tzinfo=BERLIN), "after",
        )
        body = self.get("?from=2026-11-10&days=1").json()
        self.assertEqual([e["id"] for e in body["events"]], [crossing.pk])

    def test_calendar_problems_only_for_ended_events(self):
        running = self.event(berlin(10), berlin(12), "running")
        ended = self.event(berlin(14), berlin(16), "ended")
        self.incident(running, berlin(10, 10), None)
        self.incident(ended, berlin(14, 10), berlin(14, 50))
        body = self.get("?from=2026-11-10&days=1", now=berlin(11)).json()
        by_id = {e["id"]: e for e in body["events"]}
        self.assertEqual(by_id[running.pk]["problems"], [])
        self.assertEqual(len(by_id[running.pk]["incidents"]), 1)
        # Same data, later: the first event has ended, so its problem shows.
        body = self.get("?from=2026-11-10&days=1", now=berlin(17)).json()
        by_id = {e["id"]: e for e in body["events"]}
        self.assertEqual(by_id[running.pk]["problems"][0]["kind"], "stream_missing")
        self.assertEqual(by_id[ended.pk]["problems"][0]["minutes"], 40)

    def test_calendar_query_count(self):
        first = self.event(berlin(8), berlin(9))
        self.incident(first, berlin(8, 10), berlin(8, 20))
        now = berlin(20)
        self.get("?from=2026-11-10", now=now)  # warm-up: creates the settings row
        with CaptureQueriesContext(connection) as one:
            self.assertEqual(self.get("?from=2026-11-10", now=now).status_code, 200)
        for hour in (9, 10, 11, 12):
            event = self.event(berlin(hour), berlin(hour, 30))
            self.incident(event, berlin(hour, 5), berlin(hour, 10))
        with CaptureQueriesContext(connection) as five:
            body = self.get("?from=2026-11-10", now=now).json()
        self.assertEqual(len(body["events"]), 5)
        self.assertEqual(len(one), len(five))

    def test_calendar_requires_access(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.get().status_code, 403)


class GitLabSettingsTests(TestCase):
    URL = "https://gitlab.example.com/g/p"

    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)
        self.base = self.client.get("/api/settings/monitor/").json()
        self.base.pop("gitlab_token_set", None)

    def put(self, **extra):
        return self.client.put(
            "/api/settings/monitor/",
            {**self.base, **extra},
            content_type="application/json",
        )

    def test_token_is_write_only(self):
        response = self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertNotIn("gitlab_token", body)
        self.assertIs(body["gitlab_token_set"], True)
        obj = MonitorSettings.load()
        self.assertNotEqual(obj.gitlab_token, "glpat-secret")
        self.assertEqual(obj.gitlab_token_plain(), "glpat-secret")

    def test_put_without_token_keeps_it(self):
        self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        body = self.put(gitlab_url=self.URL).json()
        self.assertIs(body["gitlab_token_set"], True)

    def test_url_change_without_token_clears_it(self):
        self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        body = self.put(gitlab_url="https://gitlab.example.com/other/p").json()
        self.assertIs(body["gitlab_token_set"], False)

    def test_url_change_with_new_token_keeps_new(self):
        self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        body = self.put(
            gitlab_url="https://gitlab.example.com/other/p", gitlab_token="glpat-new"
        ).json()
        self.assertIs(body["gitlab_token_set"], True)
        self.assertEqual(MonitorSettings.load().gitlab_token_plain(), "glpat-new")

    def test_empty_token_clears(self):
        self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        body = self.put(gitlab_url=self.URL, gitlab_token="").json()
        self.assertIs(body["gitlab_token_set"], False)

    def test_http_url_rejected_without_debug(self):
        url = "http://gitlab.example.com/g/p"
        with override_settings(DEBUG=False):
            response = self.put(gitlab_url=url)
        self.assertEqual(response.status_code, 400)
        self.assertIn("gitlab_url", response.json())
        with override_settings(DEBUG=True):
            self.assertEqual(self.put(gitlab_url=url).status_code, 200)

    def test_url_without_project_path_rejected(self):
        self.assertEqual(self.put(gitlab_url="https://gitlab.example.com/").status_code, 400)
        self.assertEqual(
            self.put(gitlab_url="https://gitlab.example.com/-/issues").status_code, 400
        )

    def test_invalid_encryption_key_gives_400_not_500(self):
        with override_settings(TOKEN_ENCRYPTION_KEY="not-a-fernet-key"):
            response = self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        self.assertEqual(response.status_code, 400)
        self.assertIn("gitlab_token", response.json())
        self.assertNotIn("glpat-secret", response.content.decode())

    def test_tickets_disabled_for_http_url_without_debug(self):
        s = MonitorSettings.load()
        s.gitlab_url = "http://gitlab.example.com/g/p"
        s.set_gitlab_token("glpat-secret")
        s.save()
        self.assertFalse(MonitorSettings.load().tickets_enabled)
        with override_settings(DEBUG=True):
            self.assertTrue(MonitorSettings.load().tickets_enabled)

    def test_url_with_userinfo_rejected(self):
        self.assertEqual(
            self.put(gitlab_url="https://u:pw@gitlab.example.com/g/p").status_code, 400
        )

    def test_whoami_tickets_enabled(self):
        self.assertIs(self.client.get("/api/whoami/").json()["tickets_enabled"], False)
        self.put(gitlab_url=self.URL, gitlab_token="glpat-secret")
        self.assertIs(self.client.get("/api/whoami/").json()["tickets_enabled"], True)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GITLAB_TOKEN = "glpat-secret-token-123"


class TicketTests(TestCase):
    """GitLab ticket endpoint; GitLab is simulated with httpx.MockTransport."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member",
            is_superuser=True,
            first_name="Erika",
            last_name="Beispiel",
            email="erika@example.org",
        )
        self.client.force_login(self.user)
        self.recorder = Recorder.objects.create(
            room_name="Hörsaal A", stream_name="cap-hs-a", agent_id="agent-a"
        )
        now = timezone_now()
        RecorderStatus.objects.update_or_create(
            recorder=self.recorder,
            defaults={
                "state": RecorderStatus.LIVE,
                "live_since": now - timedelta(hours=1),
                "agent_state": "capturing",
            },
        )
        ScheduledEvent.objects.create(
            identifier="ev-1",
            recorder=self.recorder,
            title="Mathe I",
            series="Analysis",
            presenters="Dr. Erika Muster",
            start=now - timedelta(minutes=30),
            end=now + timedelta(minutes=30),
            opencast_status="EVENTS.EVENTS.STATUS.SCHEDULED",
        )
        s = MonitorSettings.load()
        s.gitlab_url = "https://gitlab.example.com/g/p"
        s.set_gitlab_token(GITLAB_TOKEN)
        s.save()
        self.url = f"/api/recorders/{self.recorder.pk}/ticket/"
        self.requests = []

    def _mock(self, upload=None, issue=None):
        def handler(request):
            self.requests.append(request)
            path = request.url.path
            if path.endswith("/uploads"):
                return upload or httpx.Response(
                    201, json={"markdown": "![shot](/uploads/abc/shot.png)"}
                )
            if path.endswith("/issues"):
                return issue or httpx.Response(
                    201, json={"web_url": "https://gitlab.example.com/g/p/-/issues/7"}
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        return mock.patch(
            "recorders.tickets._client",
            lambda: httpx.Client(transport=transport, follow_redirects=False),
        )

    def _post(self, message="Bild gestört", shot=None, **extra):
        data = {"message": message, **extra}
        if shot is not None:
            data["screenshot"] = shot
        return self.client.post(self.url, data)

    @staticmethod
    def _form(request):
        return parse_qs(request.content.decode())

    def _png(self, name="shot.png", content=PNG):
        return SimpleUploadedFile(name, content, content_type="image/png")

    def test_parse_project_url(self):
        self.assertEqual(
            tickets.parse_project_url("https://gitlab.example.com/g/sub/p"),
            ("https://gitlab.example.com", "g/sub/p"),
        )
        self.assertEqual(
            tickets.parse_project_url("https://gitlab.example.com/g/p/-/issues?x=1#f"),
            ("https://gitlab.example.com", "g/p"),
        )
        self.assertIsNone(tickets.parse_project_url("https://gitlab.example.com/"))
        self.assertIsNone(tickets.parse_project_url("ftp://gitlab.example.com/g/p"))
        self.assertIsNone(tickets.parse_project_url("https://u:pw@gitlab.example.com/g/p"))
        # http only in DEBUG
        self.assertIsNone(tickets.parse_project_url("http://gitlab.example.com/g/p"))
        with override_settings(DEBUG=True):
            self.assertEqual(
                tickets.parse_project_url("http://gitlab.example.com/g/p"),
                ("http://gitlab.example.com", "g/p"),
            )

    def test_safe_web_url(self):
        cfg = "https://gitlab.example.com/g/p"
        ok = "https://GitLab.example.com/g/p/-/issues/1"
        self.assertEqual(tickets.safe_web_url(ok, cfg), ok)
        self.assertIsNone(tickets.safe_web_url("https://evil.example/x", cfg))
        self.assertIsNone(tickets.safe_web_url("javascript:alert(1)", cfg))
        self.assertIsNone(tickets.safe_web_url("http://gitlab.example.com/x", cfg))
        self.assertIsNone(tickets.safe_web_url(None, cfg))
        self.assertIsNone(tickets.safe_web_url(5, cfg))

    def test_safe_web_url_default_ports(self):
        got = "https://gitlab.example.com/g/p/-/issues/1"
        self.assertEqual(
            tickets.safe_web_url(got, "https://gitlab.example.com:443/g/p"), got
        )
        self.assertIsNone(
            tickets.safe_web_url(got, "https://gitlab.example.com:8443/g/p")
        )

    def test_title_shortened_single_line(self):
        message = ("Zeile eins\n" + "x" * 500 + "\nrest")
        title = tickets.build_title(self.recorder, message)
        self.assertNotIn("\n", title)
        self.assertLessEqual(len(title), 255)
        self.assertTrue(title.startswith("Hörsaal A (cap-hs-a): Zeile eins"))
        long_single = tickets.build_title(self.recorder, "y" * 500)
        self.assertEqual(len(long_single), 255)
        self.assertTrue(long_single.endswith("…"))

    def test_description_contains_details(self):
        self.recorder.refresh_from_db()
        text = tickets.build_description(
            self.recorder,
            "Bild gestört",
            self.user,
            timezone_now(),
            "![shot](/uploads/abc/shot.png)",
            None,
        )
        for needle in (
            "Bild gestört",
            "cap-hs-a",
            "agent-a",
            "Mathe I",
            "Analysis",
            "Dr. Erika Muster",
            f"/raum/{self.recorder.pk}",
            "Erika Beispiel <erika@example.org>",
            "![shot](/uploads/abc/shot.png)",
        ):
            self.assertIn(needle, text)

    def test_ticket_endpoint_uploads_and_creates(self):
        with self._mock():
            response = self._post(shot=self._png())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json(),
            {"web_url": "https://gitlab.example.com/g/p/-/issues/7"},
        )
        self.assertEqual(len(self.requests), 2)
        first, second = self.requests
        self.assertEqual(first.url.raw_path.split(b"?")[0], b"/api/v4/projects/g%2Fp/uploads")
        self.assertTrue(second.url.path.endswith("/issues"))
        self.assertEqual(second.headers["PRIVATE-TOKEN"], GITLAB_TOKEN)
        description = self._form(second)["description"][0]
        self.assertIn("uploads/abc/shot.png", description)
        self.assertIn("Mathe I", description)

    def test_upload_failure_still_creates_issue(self):
        with self._mock(upload=httpx.Response(500, text="boom")):
            response = self._post(shot=self._png())
        self.assertEqual(response.status_code, 201)
        issue = self.requests[-1]
        self.assertTrue(issue.url.path.endswith("/issues"))
        description = self._form(issue)["description"][0]
        self.assertIn("screenshot upload", description)
        self.assertNotIn("![", description)

    def test_without_screenshot(self):
        with self._mock():
            response = self._post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].url.path.endswith("/issues"))
        self.assertIn("No screenshot", self._form(self.requests[0])["description"][0])

    def test_redirect_not_followed(self):
        redirect = httpx.Response(302, headers={"Location": "https://evil.example/x"})
        with self._mock(issue=redirect):
            response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(all(r.url.host == "gitlab.example.com" for r in self.requests))

    def test_foreign_web_url_gives_success_without_link(self):
        with self._mock(issue=httpx.Response(201, json={"web_url": "https://evil.example/i/1"})):
            with self.assertLogs("recorders.tickets", level="WARNING") as logs:
                response = self._post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"web_url": None})
        self.assertNotIn(GITLAB_TOKEN, "\n".join(logs.output))

    def test_explicit_default_port_matches(self):
        s = MonitorSettings.load()
        s.gitlab_url = "https://gitlab.example.com:443/g/p"
        s.save()
        with self._mock():
            response = self._post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(), {"web_url": "https://gitlab.example.com/g/p/-/issues/7"}
        )

    def test_invalid_image_rejected(self):
        with self._mock():
            response = self._post(shot=self._png(content=b"<html>"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.requests, [])

    def test_image_too_large(self):
        with self._mock():
            response = self._post(shot=self._png(content=PNG + b"\x00" * (5 * 1024 * 1024)))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.requests, [])

    def test_blank_message_rejected(self):
        with self._mock():
            self.assertEqual(self._post(message="   ").status_code, 400)
            self.assertEqual(self._post(message="x" * 2001).status_code, 400)
        self.assertEqual(self.requests, [])

    def test_not_configured(self):
        s = MonitorSettings.load()
        s.gitlab_url = ""
        s.save()
        with self._mock():
            response = self._post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.requests, [])

    def test_requires_access(self):
        self.client.force_login(User.objects.create_user(username="out"))
        with self._mock():
            response = self._post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.requests, [])

    def test_token_not_in_error(self):
        with self._mock(issue=httpx.Response(401, json={"message": GITLAB_TOKEN})):
            with self.assertLogs("recorders.tickets", level="WARNING") as logs:
                response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn(GITLAB_TOKEN, response.content.decode())
        self.assertNotIn(GITLAB_TOKEN, "\n".join(logs.output))
