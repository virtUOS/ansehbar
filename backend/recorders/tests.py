# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Tests for recorders and monitor settings."""
import json
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from recorders.models import MonitorSettings, Recorder, RecorderStatus
from recorders.monitor import run_cycle
from streams.sources import Probe

User = get_user_model()


class RecorderApiTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username="member", is_superuser=True)
        self.client.force_login(member)

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
            row["status"], {"state": "unknown", "live_since": None, "checked_at": None}
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

    def test_delete_not_allowed(self):
        rec = Recorder.objects.create(room_name="A", stream_name="rec-a")
        response = self.client.delete(f"/api/recorders/{rec.pk}/")
        self.assertEqual(response.status_code, 405)

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
            state="live", live_since=NOW
        )
        source = FakeSource({})
        self.assertEqual(run_cycle(source, NOW), 0)
        self.assertEqual(source.probed, [])
        r.status.refresh_from_db()
        self.assertEqual(r.status.state, "unknown")
        self.assertIsNone(r.status.live_since)

    def test_run_once_command_exits(self):
        Recorder.objects.create(room_name="A", stream_name="rec-a")
        source = FakeSource({"rec-a": Probe(True, False, None, None, "HTTP 404")})
        with mock.patch(
            "recorders.management.commands.run_monitor.HlsStreamSource",
            return_value=source,
        ):
            call_command("run_monitor", "--once")
        self.assertEqual(Recorder.objects.get().status.state, "offline")


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

    def test_example_file_loads_cleanly(self):
        example = Path(settings.BASE_DIR) / "site.example.json"
        out = StringIO()
        call_command("load_site_config", "--path", str(example), stdout=out)
        self.assertIn("created: 4", out.getvalue())
        self.assertFalse(Recorder.objects.get(stream_name="rec-20-hall").active)
        self.assertIn("unchanged: 4", self.run_cmd(json.loads(example.read_text())))
