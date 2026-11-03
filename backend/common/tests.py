# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Every app keeps at least basic tests next to its code (Repo-Konvention)."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from opencast.models import OpencastSyncState
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus

from .pagination import StandardPagination


class StandardPaginationTests(SimpleTestCase):
    def _page_size(self, query):
        request = Request(APIRequestFactory().get("/", query))
        return StandardPagination().get_page_size(request)

    def test_default_page_size(self):
        self.assertEqual(self._page_size({}), 25)

    def test_client_may_pick_page_size(self):
        self.assertEqual(self._page_size({"page_size": "5"}), 5)

    def test_page_size_is_capped(self):
        self.assertEqual(self._page_size({"page_size": "5000"}), 1000)

    def test_invalid_page_size_falls_back_to_default(self):
        self.assertEqual(self._page_size({"page_size": "many"}), 25)


TOKEN = "test-metrics-token"


def _recorder(room, stream, **kwargs):
    return Recorder.objects.create(room_name=room, stream_name=stream, **kwargs)


def _open_incident(recorder, alerted):
    now = timezone.now()
    return Incident.objects.create(
        recorder=recorder,
        kind=Incident.STREAM_MISSING,
        started_at=now - timedelta(minutes=10),
        alerted_at=now if alerted else None,
    )


@override_settings(METRICS_TOKEN=TOKEN)
class MetricsTests(TestCase):
    def _get(self, token=TOKEN):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        return self.client.get("/metrics", **headers)

    def _body(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    @override_settings(METRICS_TOKEN="")
    def test_metrics_404_without_token(self):
        self.assertEqual(self._get().status_code, 404)

    def test_metrics_401_with_wrong_token(self):
        self.assertEqual(self._get("wrong").status_code, 401)
        self.assertEqual(self._get(None).status_code, 401)

    def test_metrics_401_with_non_ascii_token(self):
        self.assertEqual(self._get("tökén").status_code, 401)

    def test_metrics_content_type(self):
        self.assertEqual(
            self._get()["Content-Type"], "text/plain; version=0.0.4; charset=utf-8"
        )

    def test_stream_missing_alarm_gauge(self):
        alarmed = _recorder("Room A", "cap-90-A")
        _open_incident(alarmed, alerted=True)
        _recorder("Room B", "cap-90-B")
        _recorder("Room C", "cap-90-C", alarm_mode=Recorder.ALARM_OFF)
        _recorder("Room D", "cap-90-D", active=False)
        body = self._body()
        self.assertIn("# TYPE ansehbar_stream_missing_alarm gauge", body)
        self.assertIn(
            'ansehbar_stream_missing_alarm{room="Room A",stream="cap-90-A"} 1', body
        )
        self.assertIn(
            'ansehbar_stream_missing_alarm{room="Room B",stream="cap-90-B"} 0', body
        )
        self.assertNotIn("Room C", body)
        self.assertNotIn("Room D", body)

    def test_metrics_stream_gauge_ignores_audio(self):
        room = _recorder("Room A", "cap-90-A")
        Incident.objects.create(
            recorder=room,
            kind=Incident.AUDIO_SILENT,
            started_at=timezone.now() - timedelta(minutes=20),
            alerted_at=timezone.now(),
        )
        self.assertIn(
            'ansehbar_stream_missing_alarm{room="Room A",stream="cap-90-A"} 0',
            self._body(),
        )

    def test_audio_silent_alarm_gauge(self):
        silent = _recorder("Room A", "cap-90-A")
        Incident.objects.create(
            recorder=silent,
            kind=Incident.AUDIO_SILENT,
            started_at=timezone.now() - timedelta(minutes=20),
            alerted_at=timezone.now(),
        )
        _recorder("Room B", "cap-90-B")
        _recorder("Room C", "cap-90-C", alarm_mode=Recorder.ALARM_OFF)
        _recorder("Room D", "cap-90-D", active=False)
        body = self._body()
        self.assertIn("# TYPE ansehbar_audio_silent_alarm gauge", body)
        self.assertIn(
            'ansehbar_audio_silent_alarm{room="Room A",stream="cap-90-A"} 1', body
        )
        self.assertIn(
            'ansehbar_audio_silent_alarm{room="Room B",stream="cap-90-B"} 0', body
        )
        self.assertNotIn('ansehbar_audio_silent_alarm{room="Room C"', body)
        self.assertNotIn('ansehbar_audio_silent_alarm{room="Room D"', body)
        # a stream-missing incident does not raise the audio gauge
        self.assertIn(
            'ansehbar_stream_missing_alarm{room="Room A",stream="cap-90-A"} 0', body
        )

    def test_unalerted_or_ended_incident_is_not_an_alarm(self):
        pending = _recorder("Room A", "cap-90-A")
        _open_incident(pending, alerted=False)
        ended = _recorder("Room B", "cap-90-B")
        incident = _open_incident(ended, alerted=True)
        incident.ended_at = timezone.now()
        incident.save(update_fields=["ended_at"])
        body = self._body()
        self.assertIn('{room="Room A",stream="cap-90-A"} 0', body)
        self.assertIn('{room="Room B",stream="cap-90-B"} 0', body)

    def test_room_label_falls_back_like_the_ui(self):
        _recorder("", "cap-90-R12", agent_id="agent-7")
        _recorder("", "cap-90-R13")
        body = self._body()
        self.assertIn('room="agent-7",stream="cap-90-R12"', body)
        self.assertIn('room="cap-90-R13",stream="cap-90-R13"', body)

    def test_metrics_channel_off_hides_alarm_gauge(self):
        _recorder("Room A", "cap-90-A")
        MonitorSettings.objects.update_or_create(
            pk=1, defaults={"alarm_metrics_enabled": False}
        )
        body = self._body()
        self.assertNotIn("ansehbar_stream_missing_alarm", body)
        self.assertNotIn("ansehbar_audio_silent_alarm", body)
        self.assertIn("ansehbar_recorders", body)

    def test_label_values_are_escaped(self):
        _recorder('Room "A"\\x', "cap-90-A")
        self.assertIn(r'room="Room \"A\"\\x"', self._body())

    def test_recorder_state_counts(self):
        for stream, state in (("a", "live"), ("b", "live"), ("c", "offline")):
            RecorderStatus.objects.filter(recorder=_recorder("R", stream)).update(
                state=state
            )
        _recorder("R", "d")  # unknown
        gone = _recorder("R", "e", active=False)
        RecorderStatus.objects.filter(recorder=gone).update(state="live")
        body = self._body()
        self.assertIn('ansehbar_recorders{state="live"} 2', body)
        self.assertIn('ansehbar_recorders{state="offline"} 1', body)
        self.assertIn('ansehbar_recorders{state="unknown"} 1', body)

    def test_last_check_is_newest_check_of_active_recorders(self):
        when = timezone.now().replace(microsecond=0)
        RecorderStatus.objects.filter(recorder=_recorder("R", "a")).update(
            checked_at=when - timedelta(minutes=5)
        )
        RecorderStatus.objects.filter(recorder=_recorder("R", "b")).update(
            checked_at=when
        )
        gone = _recorder("R", "c", active=False)
        RecorderStatus.objects.filter(recorder=gone).update(
            checked_at=when + timedelta(hours=1)
        )
        self.assertIn(
            f"ansehbar_monitor_last_check_timestamp_seconds {int(when.timestamp())}",
            self._body(),
        )

    def test_last_check_absent_without_checks(self):
        _recorder("R", "a")
        self.assertNotIn("ansehbar_monitor_last_check_timestamp_seconds", self._body())

    @override_settings(OPENCAST_URL="")
    def test_opencast_disabled(self):
        OpencastSyncState.objects.update_or_create(
            pk=1, defaults={"last_success_at": timezone.now()}
        )
        body = self._body()
        self.assertIn("ansehbar_opencast_enabled 0", body)
        self.assertNotIn("ansehbar_opencast_last_success_timestamp_seconds", body)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_opencast_enabled_reports_last_success(self):
        when = timezone.now().replace(microsecond=0)
        self.assertNotIn(
            "ansehbar_opencast_last_success_timestamp_seconds", self._body()
        )
        OpencastSyncState.objects.update_or_create(
            pk=1, defaults={"last_success_at": when}
        )
        body = self._body()
        self.assertIn("ansehbar_opencast_enabled 1", body)
        self.assertIn(
            f"ansehbar_opencast_last_success_timestamp_seconds {int(when.timestamp())}",
            body,
        )


class AlertRulesTests(SimpleTestCase):
    def test_alerts_file_is_valid_yaml_with_severity(self):
        yaml = __import__("yaml")
        # The dev container mounts only backend/, so the repo root (and with it
        # monitoring/) may be invisible there; the file is then checked on the host.
        path = Path(settings.BASE_DIR).parent / "monitoring" / "alerts.yml"
        if not path.is_file():
            self.skipTest(f"{path} is not visible here (repo root not mounted)")
        data = yaml.safe_load(path.read_text())
        rules = [r for g in data["groups"] for r in g["rules"]]
        self.assertEqual(
            {r["alert"] for r in rules},
            {
                "AnsehbarStreamMissing",
                "AnsehbarAudioSilent",
                "AnsehbarMonitorStale",
                "AnsehbarOpencastSyncStale",
            },
        )
        audio = next(r for r in rules if r["alert"] == "AnsehbarAudioSilent")
        self.assertEqual(audio["labels"]["severity"], "warning")
        self.assertEqual(audio["labels"]["service"], "ansehbar")
        for rule in rules:
            self.assertIn(rule["labels"]["severity"], {"warning", "critical"})
            self.assertEqual(rule["labels"]["service"], "ansehbar")
