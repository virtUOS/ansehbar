# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Starter tests for the session endpoints; the OIDC machinery itself is
covered by basicbar-auth's package CI."""
from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class WhoamiTests(TestCase):
    def test_anonymous(self):
        payload = self.client.get("/api/whoami/").json()
        self.assertFalse(payload["authenticated"])
        # An authoritative CSRF token is returned so the SPA can send unsafe
        # requests reliably (esp. cross-origin in dev).
        self.assertTrue(payload["csrf_token"])
        self.assertIn("content_default_language", payload)

    def test_authenticated(self):
        user = User.objects.create_user(username="frank", subject="abc-123")
        self.client.force_login(user)
        payload = self.client.get("/api/whoami/").json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["username"], "frank")
        self.assertEqual(payload["subject"], "abc-123")
        self.assertFalse(payload["is_staff"])


class SetLanguageTests(TestCase):
    def test_sets_supported_language(self):
        user = User.objects.create_user(username="frank")
        self.client.force_login(user)
        response = self.client.post(
            "/api/whoami/language/", {"language": "de"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.language, "de")

    def test_rejects_unknown_language(self):
        user = User.objects.create_user(username="frank")
        self.client.force_login(user)
        response = self.client.post(
            "/api/whoami/language/", {"language": "xx"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_authentication(self):
        response = self.client.post(
            "/api/whoami/language/", {"language": "de"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
