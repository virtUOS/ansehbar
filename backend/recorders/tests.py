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
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from opencast.client import Agent, OpencastError
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from opencast.sync import sync_agents
from recorders.alarm_rules import alarm_due, alarm_threshold, slot_start
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus
from recorders.monitor import run_cycle
from streams.sources import Probe

User = get_user_model()


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
        self.event(berlin(10), berlin(12), "first")
        self.event(berlin(14), berlin(16), "second")
        body = self.get(berlin(11))
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
