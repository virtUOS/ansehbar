# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from datetime import datetime
from smtplib import SMTPException
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from alarms.delivery import deliver_alarms
from alarms.models import AlarmRecipient, SentNotification
from opencast.models import ScheduledEvent
from recorders.incidents import update_incidents
from recorders.models import Incident, MonitorSettings, Recorder, RecorderStatus

User = get_user_model()
URL = "/api/alarm-recipients/"


class AlarmRecipientApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="alice", email="alice@example.org", is_superuser=True
        )
        self.client.force_login(self.admin)

    def post(self, data, url=URL):
        return self.client.post(url, data, content_type="application/json")

    def test_add_by_email(self):
        response = self.post({"email": "ops@example.org"})
        self.assertEqual(response.status_code, 201)
        recipient = AlarmRecipient.objects.get()
        self.assertEqual(recipient.email, "ops@example.org")
        self.assertTrue(recipient.active)
        self.assertEqual(recipient.created_by, "alice")
        self.assertEqual(self.client.get(URL).json()[0]["email"], "ops@example.org")

    def test_add_by_user_takes_their_email(self):
        bob = User.objects.create_user(username="bob", email="bob@example.org")
        response = self.post({"user": bob.pk})
        self.assertEqual(response.status_code, 201)
        recipient = AlarmRecipient.objects.get()
        self.assertEqual(recipient.email, "bob@example.org")
        self.assertEqual(recipient.user, bob)

    def test_user_without_email_is_400(self):
        carl = User.objects.create_user(username="carl", email="")
        response = self.post({"user": carl.pk})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AlarmRecipient.objects.exists())

    def test_duplicate_is_400(self):
        AlarmRecipient.objects.create(email="ops@example.org")
        response = self.post({"email": "OPS@example.org"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AlarmRecipient.objects.count(), 1)

    def test_toggle_and_delete(self):
        recipient = AlarmRecipient.objects.create(email="ops@example.org")
        url = f"{URL}{recipient.pk}/"
        response = self.client.patch(
            url, {"active": False}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        self.assertFalse(recipient.active)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(AlarmRecipient.objects.exists())

    def test_requires_access(self):
        self.client.force_login(User.objects.create_user(username="nobody"))
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.post({"email": "x@example.org"}).status_code, 403)
        self.assertEqual(self.post({}, url=URL + "test/").status_code, 403)

    def test_test_endpoint_queues_one_per_active_recipient(self):
        AlarmRecipient.objects.create(email="a@example.org")
        AlarmRecipient.objects.create(email="b@example.org")
        AlarmRecipient.objects.create(email="c@example.org", active=False)
        response = self.post({}, url=URL + "test/")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"queued": 2})
        notes = SentNotification.objects.filter(kind="test")
        self.assertEqual(
            sorted(n.recipient for n in notes), ["a@example.org", "b@example.org"]
        )
        for n in notes:
            self.assertRegex(n.key, rf"^test:[0-9a-f-]{{36}}:email:{n.recipient}$")
            self.assertIsNone(n.sent_at)
            self.assertEqual(n.attempts, 0)


BERLIN = ZoneInfo("Europe/Berlin")
MONITOR = "recorders.management.commands.run_monitor"


def berlin(hour, minute=0, second=0, day=10):
    """Local time on 2026-11-<day> (CET)."""
    return datetime(2026, 11, day, hour, minute, second, tzinfo=BERLIN)


@override_settings(
    ALARM_LANGUAGE="de",
    FRONTEND_BASE_URL="https://ansehbar.example.org",
    DEFAULT_FROM_EMAIL="ansehbar@example.org",
)
class DeliveryTests(TestCase):
    """Event 10:00-12:00 local, grace 3 min, c.t. 15 + 5 min, 2-hour slots."""

    def setUp(self):
        MonitorSettings.objects.update_or_create(
            pk=1,
            defaults={
                "missing_grace_minutes": 3,
                "ct_minutes": 15,
                "ct_tolerance_minutes": 5,
                "slot_minutes": 120,
                "slot_offset_minutes": 0,
            },
        )
        Recorder.objects.all().delete()
        self.recorder = Recorder.objects.create(
            room_name="Hörsaal A", stream_name="cap-A-01"
        )
        self.status, _ = RecorderStatus.objects.get_or_create(recorder=self.recorder)
        self.event = ScheduledEvent.objects.create(
            identifier="ev-1",
            recorder=self.recorder,
            title="Lineare Algebra",
            series="Mathematik I",
            start=berlin(10),
            end=berlin(12),
        )
        AlarmRecipient.objects.create(email="a@example.org")
        AlarmRecipient.objects.create(email="b@example.org")
        AlarmRecipient.objects.create(email="c@example.org", active=False)

    def set_state(self, state, offline_since=None):
        self.status.state = state
        self.status.offline_since = offline_since
        self.status.save()

    def cycle(self, now):
        update_incidents(now)
        deliver_alarms(now)

    def incident(self, started_at=None, **kwargs):
        kwargs.setdefault("event", self.event)
        return Incident.objects.create(
            recorder=self.recorder,
            kind=Incident.STREAM_MISSING,
            started_at=started_at or berlin(10, 3),
            **kwargs,
        )

    def subjects(self):
        return sorted(m.subject for m in mail.outbox)

    def test_alarm_sent_once_to_each_active_recipient(self):
        incident = self.incident()
        deliver_alarms(berlin(10, 5))
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox), ["a@example.org", "b@example.org"]
        )
        self.assertTrue(all(len(m.to) == 1 for m in mail.outbox))
        self.assertEqual(mail.outbox[0].from_email, "ansehbar@example.org")
        incident.refresh_from_db()
        self.assertEqual(incident.alerted_at, berlin(10, 5))
        notes = SentNotification.objects.order_by("recipient")
        self.assertEqual(
            [n.key for n in notes],
            [
                f"incident:{incident.pk}:alarm:email:a@example.org",
                f"incident:{incident.pk}:alarm:email:b@example.org",
            ],
        )
        self.assertTrue(all(n.sent_at == berlin(10, 5) for n in notes))
        self.assertTrue(all(n.kind == "alarm" and n.incident == incident for n in notes))

    def test_restart_does_not_resend(self):
        self.incident()
        deliver_alarms(berlin(10, 5))
        deliver_alarms(berlin(10, 6))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(SentNotification.objects.count(), 2)

    def test_not_due_before_threshold(self):
        incident = self.incident()
        deliver_alarms(berlin(10, 2))
        self.assertEqual(mail.outbox, [])
        incident.refresh_from_db()
        self.assertIsNone(incident.alerted_at)

    def test_grid_mode_waits_for_ct(self):
        self.recorder.alarm_mode = Recorder.ALARM_GRID
        self.recorder.save()
        incident = self.incident()
        deliver_alarms(berlin(10, 19))
        self.assertEqual(mail.outbox, [])
        deliver_alarms(berlin(10, 20))
        self.assertEqual(len(mail.outbox), 2)
        incident.refresh_from_db()
        self.assertEqual(incident.alerted_at, berlin(10, 20))

    def test_email_channel_off_sets_alerted_but_sends_nothing(self):
        MonitorSettings.objects.filter(pk=1).update(alarm_email_enabled=False)
        incident = self.incident()
        deliver_alarms(berlin(10, 5))
        incident.refresh_from_db()
        self.assertEqual(incident.alerted_at, berlin(10, 5))
        self.assertEqual(mail.outbox, [])
        self.assertFalse(SentNotification.objects.exists())

    def test_all_clear_after_stable_return(self):
        self.set_state("offline", berlin(9, 50))
        self.cycle(berlin(10, 5))
        self.assertEqual(len(mail.outbox), 2)
        self.set_state("live")
        self.cycle(berlin(10, 20))
        self.cycle(berlin(10, 20, 30))
        self.assertEqual(len(mail.outbox), 2)
        self.cycle(berlin(10, 21, 1))
        self.assertEqual(
            self.subjects(),
            ["[ansehBAR] Stream fehlt: Hörsaal A"] * 2
            + ["[ansehBAR] Stream wieder da: Hörsaal A"] * 2,
        )
        incident = Incident.objects.get()
        self.assertEqual(incident.all_clear_at, berlin(10, 21, 1))
        key = f"incident:{incident.pk}:all_clear:email:a@example.org"
        note = SentNotification.objects.get(key=key)
        self.assertIn("Wieder da seit: 10:20", note.body)
        self.assertIn("Fehlt seit: 10:03", note.body)
        self.cycle(berlin(10, 30))
        self.assertEqual(len(mail.outbox), 4)

    def test_no_all_clear_when_event_ends_missing(self):
        self.set_state("offline", berlin(9, 50))
        self.cycle(berlin(10, 5))
        self.cycle(berlin(12, 5))
        self.cycle(berlin(12, 10))
        self.assertEqual(self.subjects(), ["[ansehBAR] Stream fehlt: Hörsaal A"] * 2)
        incident = Incident.objects.get()
        self.assertEqual(incident.ended_at, berlin(12))
        self.assertIsNone(incident.all_clear_at)

    def test_no_all_clear_without_alarm(self):
        # The stream came back before the alarm threshold: nothing at all.
        self.set_state("offline", berlin(9, 50))
        update_incidents(berlin(10, 2, 30))
        self.set_state("live")
        self.cycle(berlin(10, 2, 50))
        self.cycle(berlin(10, 10))
        self.assertEqual(mail.outbox, [])

    def test_flicker_sends_single_alarm(self):
        self.set_state("offline", berlin(9, 50))
        self.cycle(berlin(10, 5))
        self.set_state("live")
        self.cycle(berlin(10, 20))
        self.set_state("offline", berlin(10, 20, 30))
        self.cycle(berlin(10, 20, 40))
        self.cycle(berlin(10, 21, 30))
        self.cycle(berlin(10, 25))
        self.assertEqual(self.subjects(), ["[ansehBAR] Stream fehlt: Hörsaal A"] * 2)
        incident = Incident.objects.get()
        self.assertIsNone(incident.ended_at)
        self.assertIsNone(incident.all_clear_at)

    def test_drop_after_all_clear_opens_new_incident_and_alarms(self):
        # The drop at 10:20:50 is within 60 s of the return, but noticed only
        # after the all-clear went out: a new incident with its own alarm.
        self.set_state("offline", berlin(9, 50))
        self.cycle(berlin(10, 5))
        self.set_state("live")
        self.cycle(berlin(10, 20))
        self.cycle(berlin(10, 21, 1))
        self.set_state("offline", berlin(10, 20, 50))
        self.cycle(berlin(10, 21, 10))
        first, second = Incident.objects.order_by("started_at", "pk")
        self.assertEqual(first.ended_at, berlin(10, 20))
        self.assertEqual(first.all_clear_at, berlin(10, 21, 1))
        self.assertIsNone(second.ended_at)
        self.assertEqual(second.started_at, berlin(10, 20, 50))
        self.assertEqual(second.alerted_at, berlin(10, 21, 10))
        self.assertEqual(
            self.subjects(),
            ["[ansehBAR] Stream fehlt: Hörsaal A"] * 4
            + ["[ansehBAR] Stream wieder da: Hörsaal A"] * 2,
        )

    def test_deactivated_recorder_not_alarmed(self):
        self.recorder.active = False
        self.recorder.save()
        incident = self.incident()
        deliver_alarms(berlin(10, 5))
        self.assertEqual(mail.outbox, [])
        incident.refresh_from_db()
        self.assertIsNone(incident.alerted_at)

    def test_past_event_incident_not_alarmed(self):
        old = ScheduledEvent.objects.create(
            identifier="ev-old",
            recorder=self.recorder,
            start=berlin(10, day=9),
            end=berlin(12, day=9),
        )
        incident = self.incident(started_at=berlin(10, 3, day=9), event=old)
        deliver_alarms(berlin(10, 5))
        self.assertEqual(mail.outbox, [])
        incident.refresh_from_db()
        self.assertIsNone(incident.alerted_at)

    def test_smtp_failure_is_retried_and_capped(self):
        self.incident()
        with mock.patch(
            "alarms.delivery.send_mail", side_effect=SMTPException("boom")
        ) as send, self.assertLogs("alarms.delivery", level="WARNING"):
            for minute in range(5, 11):
                deliver_alarms(berlin(10, minute))
        self.assertEqual(send.call_count, 10)  # 2 recipients x 5 attempts
        for note in SentNotification.objects.all():
            self.assertEqual(note.attempts, 5)
            self.assertIsNone(note.sent_at)
            self.assertIn("boom", note.last_error)

    def test_one_failure_does_not_block_others(self):
        self.incident()
        real = mail.send_mail

        def flaky(subject, message, from_email, recipient_list, **kwargs):
            if recipient_list == ["a@example.org"]:
                raise SMTPException("refused")
            return real(subject, message, from_email, recipient_list, **kwargs)

        with mock.patch("alarms.delivery.send_mail", side_effect=flaky), \
                self.assertLogs("alarms.delivery", level="WARNING"):
            deliver_alarms(berlin(10, 5))
        self.assertEqual([m.to for m in mail.outbox], [["b@example.org"]])
        failed = SentNotification.objects.get(recipient="a@example.org")
        self.assertEqual(failed.attempts, 1)
        self.assertIn("refused", failed.last_error)
        deliver_alarms(berlin(10, 6))
        self.assertEqual(len(mail.outbox), 2)
        failed.refresh_from_db()
        self.assertIsNotNone(failed.sent_at)

    def test_message_content(self):
        incident = self.incident()
        deliver_alarms(berlin(10, 5))
        message = next(m for m in mail.outbox if m.to == ["a@example.org"])
        self.assertEqual(message.subject, "[ansehBAR] Stream fehlt: Hörsaal A")
        body = message.body
        self.assertIn("Hörsaal A", body)
        self.assertIn("cap-A-01", body)
        self.assertIn("Stream fehlt", body)
        self.assertIn("Lineare Algebra", body)
        self.assertIn("Mathematik I", body)
        self.assertIn("10:00–12:00", body)
        self.assertIn("10.11.2026", body)
        self.assertIn("Fehlt seit: 10:03", body)
        self.assertIn(
            f"https://ansehbar.example.org/raum/{self.recorder.pk}", body
        )
        self.assertNotIn("&", body)
        self.assertEqual(incident.recorder.stream_name, "cap-A-01")

    @override_settings(ALARM_LANGUAGE="en", FRONTEND_BASE_URL="https://x.example.org/")
    def test_message_in_english_and_room_fallback(self):
        self.recorder.room_name = "  "
        self.recorder.agent_id = "agent-7"
        self.recorder.save()
        self.incident()
        deliver_alarms(berlin(10, 5))
        message = mail.outbox[0]
        self.assertEqual(message.subject, "[ansehBAR] Stream missing: agent-7")
        self.assertIn("Missing since: 10:03", message.body)
        self.assertIn(f"https://x.example.org/raum/{self.recorder.pk}", message.body)

    def test_room_falls_back_to_stream_name(self):
        self.recorder.room_name = ""
        self.recorder.save()
        self.incident()
        deliver_alarms(berlin(10, 5))
        self.assertEqual(mail.outbox[0].subject, "[ansehBAR] Stream fehlt: cap-A-01")

    def test_test_notification_is_sent(self):
        SentNotification.objects.create(
            key="test:1:email:a@example.org",
            kind=SentNotification.TEST,
            recipient="a@example.org",
        )
        deliver_alarms(berlin(10, 5))
        (message,) = mail.outbox
        self.assertEqual(message.subject, "[ansehBAR] Testalarm")
        self.assertEqual(message.to, ["a@example.org"])
        self.assertTrue(message.body)
        note = SentNotification.objects.get()
        self.assertEqual(note.subject, "[ansehBAR] Testalarm")
        self.assertEqual(note.sent_at, berlin(10, 5))

    def test_unexpected_error_is_logged_not_raised(self):
        self.incident()
        with mock.patch(
            "alarms.delivery.alarm_due", side_effect=RuntimeError("x")
        ), self.assertLogs("alarms.delivery", level="ERROR"):
            deliver_alarms(berlin(10, 5))
        self.assertEqual(mail.outbox, [])

    @override_settings(OPENCAST_URL="")
    def test_run_monitor_calls_delivery_and_survives_its_errors(self):
        with mock.patch(f"{MONITOR}.run_cycle", return_value=0), \
                mock.patch(f"{MONITOR}.update_incidents"), \
                mock.patch(
                    f"{MONITOR}.deliver_alarms", side_effect=RuntimeError("x")
                ) as deliver, \
                self.assertLogs(MONITOR, level="INFO") as logs:
            call_command("run_monitor", "--once")
        deliver.assert_called_once()
        self.assertTrue(any("delivering alarms failed" in m for m in logs.output))
        self.assertFalse(any("monitor cycle failed" in m for m in logs.output))
        self.assertTrue(any("monitor cycle:" in m for m in logs.output))
