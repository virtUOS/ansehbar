# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Validators for stream names and the playback URL template."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError

STREAM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_stream_name(value: str) -> None:
    # fullmatch semantics: "$" would accept a trailing newline.
    if not STREAM_NAME_RE.fullmatch(value or ""):
        raise ValidationError(
            "Only letters, digits, '.', '_' and '-' are allowed "
            "(must start with a letter or digit)."
        )


def validate_url_template(value: str) -> None:
    allowed = ("https://", "http://") if settings.DEBUG else ("https://",)
    if not value.startswith(allowed):
        raise ValidationError("The URL template must start with https://.")
    if value.count("{stream}") != 1:
        raise ValidationError("The URL template must contain {stream} exactly once.")
    # Reject any other brace usage that would break str.format().
    if "{" in value.replace("{stream}", "") or "}" in value.replace("{stream}", ""):
        raise ValidationError("The URL template must not contain other braces.")
