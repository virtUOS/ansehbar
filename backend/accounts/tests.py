# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Starter tests for the session endpoints; the OIDC machinery itself is
covered by basicbar-auth's package CI."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from accounts.access import has_access
from accounts.models import Invitation

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


class HasAccessTests(TestCase):
    def test_group_claim_grants_access(self):
        user = User.objects.create_user(
            username="a", claims={"groups": ["ansehbar-users"]}
        )
        self.assertTrue(has_access(user))

    def test_group_claim_as_string(self):
        user = User.objects.create_user(
            username="a", claims={"groups": "ansehbar-users"}
        )
        self.assertTrue(has_access(user))

    def test_no_group_no_invite_denied(self):
        user = User.objects.create_user(username="a", claims={"groups": ["other"]})
        self.assertFalse(has_access(user))

    def test_invitation_by_username_case_insensitive(self):
        Invitation.objects.create(identifier=" Max.Muster ")
        user = User.objects.create_user(username="max.muster")
        self.assertTrue(has_access(user))

    def test_invitation_by_email_when_username_differs(self):
        Invitation.objects.create(identifier="max@example.org")
        user = User.objects.create_user(
            username="xyz123", email="Max@example.org"
        )
        self.assertTrue(has_access(user))

    def test_user_without_email_not_matched_by_empty_invite(self):
        user = User.objects.create_user(username="a", email="")
        self.assertFalse(has_access(user))
        with self.assertRaises(ValidationError):
            Invitation.objects.create(identifier="   ")

    @override_settings(ANSEHBAR_BOOTSTRAP_USERS=["Boss"])
    def test_bootstrap_user(self):
        user = User.objects.create_user(username="boss")
        self.assertTrue(has_access(user))

    def test_superuser_always_has_access(self):
        user = User.objects.create_superuser(username="root", password="x")
        self.assertTrue(has_access(user))

    def test_anonymous_denied(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(has_access(AnonymousUser()))


class AccessApiTests(TestCase):
    def _member(self, username="member"):
        return User.objects.create_user(
            username=username, claims={"groups": ["ansehbar-users"]}
        )

    def test_revoked_invitation_denies_next_request(self):
        invitation = Invitation.objects.create(identifier="guest")
        guest = User.objects.create_user(username="guest")
        self.client.force_login(guest)
        self.assertEqual(self.client.get("/api/invitations/").status_code, 200)
        invitation.delete()
        self.assertEqual(self.client.get("/api/invitations/").status_code, 403)

    def test_whoami_reports_has_access_false_for_outsider(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        with override_settings(ANSEHBAR_ACCESS_CONTACT="help@example.org"):
            payload = self.client.get("/api/whoami/").json()
        self.assertIs(payload["has_access"], False)
        self.assertEqual(payload["access_contact"], "help@example.org")

    def test_whoami_reports_has_access_true_for_member(self):
        self.client.force_login(self._member())
        self.assertIs(self.client.get("/api/whoami/").json()["has_access"], True)

    def test_invitations_api_requires_access(self):
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/api/invitations/").status_code, 403)

        member = self._member()
        self.client.force_login(member)
        response = self.client.post(
            "/api/invitations/",
            {"identifier": "Max.Muster", "note": "Hiwi"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["identifier"], "max.muster")
        self.assertEqual(body["created_by_name"], "member")
        duplicate = self.client.post(
            "/api/invitations/",
            {"identifier": " MAX.muster "},
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 400)
        listing = self.client.get("/api/invitations/").json()
        self.assertIsInstance(listing, list)
        self.assertEqual(len(listing), 1)

    def test_invitation_destroy(self):
        self.client.force_login(self._member())
        invitation = Invitation.objects.create(identifier="x")
        response = self.client.delete(f"/api/invitations/{invitation.pk}/")
        self.assertEqual(response.status_code, 204)

    def test_user_search_limited_and_requires_access(self):
        for i in range(25):
            User.objects.create_user(username=f"stud{i:02d}", email=f"s{i}@x.de")
        User.objects.create_user(
            username="other", first_name="Erika", last_name="Mustermann"
        )
        self.assertEqual(self.client.get("/api/users/?search=stud").status_code, 403)
        outsider = User.objects.create_user(username="out")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get("/api/users/?search=stud").status_code, 403)

        self.client.force_login(self._member())
        response = self.client.get("/api/users/?search=stud")
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results), 20)
        self.assertEqual(
            set(results[0]), {"id", "username", "email", "display_name"}
        )
        by_name = self.client.get("/api/users/?search=Mustermann").json()
        self.assertEqual([u["username"] for u in by_name], ["other"])
        by_mail = self.client.get("/api/users/?search=s7@x").json()
        self.assertEqual([u["username"] for u in by_mail], ["stud07"])
