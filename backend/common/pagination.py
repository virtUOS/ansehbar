# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Default pagination that lets the client pick the page size.

Lists that page and sort client-side fetch the full set with a large
``page_size``; the shape stays ``{count, results}`` for every caller."""
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 1000
