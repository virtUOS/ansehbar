# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib.auth import get_user_model
from django.test import TestCase

from alarms.models import AlarmRecipient, SentNotification

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
