# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.apps import AppConfig


class RecordersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "recorders"

    def ready(self):
        from recorders import signals  # noqa: F401
