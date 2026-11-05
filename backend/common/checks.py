# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.core.checks import Error, register

from common.encryption import EncryptionKeyError, _fernet


@register()
def token_encryption_key_check(app_configs, **kwargs):
    from django.conf import settings

    if not settings.TOKEN_ENCRYPTION_KEY:
        return []
    try:
        _fernet()
    except EncryptionKeyError:
        return [
            Error(
                "TOKEN_ENCRYPTION_KEY is set but not a valid Fernet key.",
                hint=(
                    "Generate one with: python -c \"from cryptography.fernet "
                    "import Fernet; print(Fernet.generate_key().decode())\""
                ),
                id="common.E001",
            )
        ]
    return []
