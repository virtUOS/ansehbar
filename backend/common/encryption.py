# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Symmetric encryption for secrets stored at rest (e.g. the GitLab project
access token).

Uses Fernet (AES-128-CBC + HMAC) from the ``cryptography`` package. The key
comes from ``settings.TOKEN_ENCRYPTION_KEY`` when set; otherwise it is derived
deterministically from ``DJANGO_SECRET_KEY`` so the feature works out of the
box. Decryption failures (e.g. the key changed) degrade gracefully to an empty
value rather than raising, so a key mismatch disables the integration instead
of breaking the page.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


class EncryptionKeyError(ValueError):
    """``TOKEN_ENCRYPTION_KEY`` is set but not a valid Fernet key."""


def _fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY
    if key:
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except ValueError:
            raise EncryptionKeyError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from None
    # Derive a valid 32-byte urlsafe-base64 Fernet key from the secret key.
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    """Encrypt plaintext to a storable token; empty stays empty."""
    if not text:
        return ""
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a stored token; empty (or undecryptable) yields an empty string."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except EncryptionKeyError:
        logger.warning("TOKEN_ENCRYPTION_KEY is not a valid Fernet key; secrets unreadable.")
        return ""
    except (InvalidToken, ValueError):
        logger.warning(
            "Could not decrypt a stored secret — TOKEN_ENCRYPTION_KEY changed?"
        )
        return ""
