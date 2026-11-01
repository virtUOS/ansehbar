# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Seed the recorders of the old static monitor (copied as a literal)."""
from django.db import migrations

# Spelling is copied exactly from the old monitor; stream names are case-sensitive.
STREAM_NAMES = [
    "cap-10-r16",
    "rec-10-r01",
    "rec-hall",
    "rec-20-r24",
    "rec-20-r25",
    "rec-40-r05",
    "rec-40-r08",
    "rec-40-r09",
    "cap-40-r19",
    "rec-40-r22",
    "rec-40-r23",
    "rec-40-r27",
    "rec-40-r28",
    "rec-30-r29",
    "rec-50-r16",
    "rec-50-r26",
    "rec-60-r18",
    "rec-60-r20",
    "cap-70-r01",
    "rec-70-r09",
    "cap-70-r10",
    "rec-80-r21",
    "rec-85-r03",
    "rec-85-r04",
    "rec-90-r01",
    "cap-90-r12",
    "cap-90-r13",
    "rec-90-r17",
    "rec-95-r02",
    "rec-95-r14",
    "rec-95-r15",
    "cap-95-r05",
    "cap-95-r11",
]

ROOM_NAME_OVERRIDES = {"rec-hall": "20/R06 (Hall)"}


def room_name(stream_name):
    if stream_name in ROOM_NAME_OVERRIDES:
        return ROOM_NAME_OVERRIDES[stream_name]
    return stream_name.split("-", 1)[1].replace("-", "/").upper()


def seed(apps, schema_editor):
    Recorder = apps.get_model("recorders", "Recorder")
    RecorderStatus = apps.get_model("recorders", "RecorderStatus")
    for name in STREAM_NAMES:
        recorder, _ = Recorder.objects.get_or_create(
            stream_name=name,
            defaults={"room_name": room_name(name), "active": True, "needs_review": False},
        )
        # Signals do not fire for historical models, so create the status here.
        RecorderStatus.objects.get_or_create(recorder=recorder)


class Migration(migrations.Migration):
    dependencies = [("recorders", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
