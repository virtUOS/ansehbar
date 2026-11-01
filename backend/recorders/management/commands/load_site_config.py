# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Load recorders and the stream URL template from a local JSON file.

`manage.py load_site_config [--path PATH|-] [--deactivate-missing] [--dry-run]`
"""
import json
import sys
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from recorders.models import MonitorSettings, Recorder
from recorders.validators import validate_stream_name, validate_url_template


def parse_config(raw: str) -> dict:
    """Validate the whole document; raise CommandError listing all problems."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandError("Invalid site config: top level must be an object.")

    problems = []
    unknown = set(data) - {"stream_url_template", "recorders"}
    if unknown:
        problems.append(f"unknown top-level keys: {', '.join(sorted(unknown))}")

    template = data.get("stream_url_template")
    if "stream_url_template" in data:
        if not isinstance(template, str):
            problems.append("stream_url_template: must be a string")
        else:
            try:
                validate_url_template(template)
            except ValidationError as exc:
                problems.append(f"stream_url_template: {' '.join(exc.messages)}")

    recorders = data.get("recorders")
    entries = []
    if not isinstance(recorders, list):
        problems.append("recorders: required, must be a list")
    else:
        seen = set()
        for i, item in enumerate(recorders):
            where = f"recorders[{i}]"
            if not isinstance(item, dict):
                problems.append(f"{where}: must be an object")
                continue
            extra = set(item) - {"stream_name", "room_name", "active"}
            if extra:
                problems.append(f"{where}: unknown keys: {', '.join(sorted(extra))}")
            stream = item.get("stream_name")
            room = item.get("room_name")
            active = item.get("active", True)
            ok = True
            if not isinstance(stream, str) or not stream:
                problems.append(f"{where}: stream_name required (string)")
                ok = False
            else:
                where = f"{where} ({stream})"
                try:
                    validate_stream_name(stream)
                except ValidationError as exc:
                    problems.append(f"{where}: stream_name: {' '.join(exc.messages)}")
                    ok = False
                if stream in seen:
                    problems.append(f"{where}: duplicate stream_name")
                    ok = False
                seen.add(stream)
            max_len = Recorder._meta.get_field("room_name").max_length
            if not isinstance(room, str) or not room.strip():
                problems.append(f"{where}: room_name required (non-empty string)")
                ok = False
            elif len(room) > max_len:
                problems.append(f"{where}: room_name longer than {max_len} characters")
                ok = False
            if not isinstance(active, bool):
                problems.append(f"{where}: active must be true or false")
                ok = False
            if ok:
                entries.append((stream, room, active))

    if problems:
        raise CommandError(
            "Invalid site config:\n" + "\n".join(f"  - {p}" for p in problems)
        )
    return {"template": template, "recorders": entries}


class Command(BaseCommand):
    help = "Load recorders and the stream URL template from a local JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=None,
            help="JSON file (default: settings.ANSEHBAR_SITE_CONFIG); '-' reads stdin.",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Set active=False for recorders not listed in the file (never deletes).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report changes without writing."
        )

    def handle(self, *args, **opts):
        path = opts["path"] or settings.ANSEHBAR_SITE_CONFIG
        if path == "-":
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                raise CommandError(f"Cannot read {path}: {exc.strerror}") from exc
        config = parse_config(raw)

        created, updated, unchanged, deactivated = [], [], [], []
        template_changed = False
        with transaction.atomic():
            listed = set()
            for stream, room, active in config["recorders"]:
                listed.add(stream)
                rec = Recorder.objects.filter(stream_name=stream).first()
                if rec is None:
                    Recorder.objects.create(
                        stream_name=stream, room_name=room, active=active
                    )
                    created.append(stream)
                elif rec.room_name != room or rec.active != active:
                    rec.room_name, rec.active = room, active
                    rec.save()
                    updated.append(stream)
                else:
                    unchanged.append(stream)
            if opts["deactivate_missing"]:
                for rec in Recorder.objects.filter(active=True).exclude(
                    stream_name__in=listed
                ):
                    rec.active = False
                    rec.save()
                    deactivated.append(rec.stream_name)
            if config["template"] is not None:
                ms = MonitorSettings.load()
                if ms.url_template != config["template"]:
                    ms.url_template = config["template"]
                    ms.save()
                    template_changed = True
            if opts["dry_run"]:
                transaction.set_rollback(True)

        prefix = "[dry-run] " if opts["dry_run"] else ""
        self.stdout.write(
            f"{prefix}created: {len(created)}, updated: {len(updated)}, "
            f"unchanged: {len(unchanged)}, deactivated: {len(deactivated)}, "
            f"template changed: {'yes' if template_changed else 'no'}"
        )
