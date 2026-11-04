# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Parsing of the configured GitLab project URL."""

from urllib.parse import urlsplit

from django.conf import settings


def parse_project_url(url: str) -> tuple[str, str] | None:
    """``https://host/g/sub/p[/-/...]`` -> ``("https://host", "g/sub/p")``.

    Query, fragment and ``/-/`` suffix are dropped. URLs with userinfo, a
    non-http(s) scheme (``http`` only in DEBUG) or without a project path
    are rejected.
    """
    try:
        parts = urlsplit((url or "").strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    allowed = ("https", "http") if settings.DEBUG else ("https",)
    if scheme not in allowed or not host:
        return None
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        return None
    project = ("/" + parts.path.strip("/")).split("/-/", 1)[0].strip("/")
    if not project:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}", project
