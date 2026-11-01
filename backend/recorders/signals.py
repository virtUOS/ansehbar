# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Every new recorder gets its status row."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from recorders.models import Recorder, RecorderStatus


@receiver(post_save, sender=Recorder)
def create_status(sender, instance, created, **kwargs):
    if created:
        RecorderStatus.objects.get_or_create(recorder=instance)
