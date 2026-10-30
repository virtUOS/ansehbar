# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Tests for recorders, monitor settings and the seed data."""
from datetime import datetime, timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
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


class SeedTests(TestCase):
    def test_seed_created_33_active_recorders(self):
        self.assertEqual(Recorder.objects.count(), 33)
        self.assertEqual(Recorder.objects.filter(active=True).count(), 33)
        self.assertEqual(RecorderStatus.objects.count(), 33)
        self.assertEqual(
            Recorder.objects.get(stream_name="rec-hall").room_name, "20/R06 (Hall)"
        )
        self.assertEqual(
            Recorder.objects.get(stream_name="cap-90-r12").room_name, "90/R12"
        )
        self.assertEqual(
            Recorder.objects.get(stream_name="cap-10-r16").room_name, "10/R16"
        )
        self.assertEqual(
            Recorder.objects.get(stream_name="rec-40-r28").room_name, "40/R28"
        )


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
        Recorder.objects.all().delete()  # drop seeded recorders

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
