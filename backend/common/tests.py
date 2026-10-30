# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Every app keeps at least basic tests next to its code (Repo-Konvention)."""
from django.test import SimpleTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

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
