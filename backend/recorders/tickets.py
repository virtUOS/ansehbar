# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Create GitLab issues for a recorder (status, Opencast details, screenshot).

The GitLab client lives in ``basicbar_integrations.gitlab`` (only ``POST .../uploads``
and ``POST .../issues`` are sent, no redirects, the token only travels to the configured
host and never appears in exceptions, logs or responses). This module keeps the ticket
text and the warnings with the recorder id.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from basicbar_integrations.gitlab import GitLabError, create_issue, parse_project_url, upload_file
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from opencast.models import ScheduledEvent
from recorders.models import MonitorSettings

__all__ = ["GitLabError", "build_description", "build_title", "create_ticket"]

logger = logging.getLogger(__name__)

TITLE_MAX = 255
BERLIN = ZoneInfo("Europe/Berlin")


def _room(recorder) -> str:
    return recorder.room_name or recorder.stream_name


def build_title(recorder, message: str) -> str:
    lines = message.strip().splitlines()
    first = " ".join(lines[0].split()) if lines else ""
    title = f"{_room(recorder)} ({recorder.stream_name}): {first}"
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rstrip() + "…"
    return title


def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return timezone.localtime(dt, BERLIN).strftime("%d.%m.%Y %H:%M")


def _current_event(recorder, now: datetime):
    return (
        ScheduledEvent.objects.filter(recorder=recorder, start__lte=now, end__gt=now)
        .order_by("start")
        .first()
    )


def _creator(user) -> str:
    name = (user.get_full_name() or "").strip()
    email = (user.email or "").strip()
    if name and email:
        return f"{name} <{email}>"
    return name or email or user.get_username()


def _status_lines(recorder) -> list[str]:
    status = getattr(recorder, "status", None)
    if status is None:
        return [_("- Status: unknown")]
    lines = []
    if status.state == "live":
        line = _("- Status: live")
        if status.live_since:
            line += " " + _("since %(time)s") % {"time": _fmt(status.live_since)}
        lines.append(line)
    elif status.state == "offline":
        line = _("- Status: offline")
        if status.offline_since:
            line += " " + _("since %(time)s") % {"time": _fmt(status.offline_since)}
        lines.append(line)
    else:
        lines.append(_("- Status: unknown"))
    if status.silent_since:
        lines.append(
            _("- Audio: silent since %(time)s") % {"time": _fmt(status.silent_since)}
        )
    if status.audio_level_db is not None:
        lines.append(_("- Audio level: %(db).1f dBFS") % {"db": status.audio_level_db})
    if status.agent_state:
        lines.append(_("- Opencast agent state: %(state)s") % {"state": status.agent_state})
    return lines


def build_description(
    recorder,
    message: str,
    user,
    now: datetime,
    image_markdown: str | None,
    screenshot_note: str | None,
) -> str:
    parts = [message.strip(), ""]
    parts += [
        "### " + _("Recorder"),
        _("- Room: %(room)s") % {"room": _room(recorder)},
        _("- Stream: %(stream)s") % {"stream": recorder.stream_name},
        _("- Capture agent: %(agent)s") % {"agent": recorder.agent_id or "–"},
        _("- Reported: %(time)s") % {"time": _fmt(now)},
        "",
        "### " + _("Status in ansehBAR"),
        *_status_lines(recorder),
        "",
        "### " + _("Current Opencast event"),
    ]
    event = _current_event(recorder, now)
    if event is None:
        parts.append(_("- No current event"))
    else:
        parts.append(_("- Title: %(title)s") % {"title": event.title or event.identifier})
        if event.series:
            parts.append(_("- Series: %(series)s") % {"series": event.series})
        if event.presenters:
            parts.append(_("- Presenters: %(names)s") % {"names": event.presenters})
        parts.append(
            _("- Scheduled: %(start)s to %(end)s")
            % {"start": _fmt(event.start), "end": _fmt(event.end)}
        )
        if event.opencast_status:
            parts.append(
                _("- Opencast status: %(status)s") % {"status": event.opencast_status}
            )
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    parts += [
        "",
        _("Reported by %(user)s") % {"user": _creator(user)},
        "",
        _("[Open room in ansehBAR](%(url)s)") % {"url": f"{base}/raum/{recorder.pk}"},
        "",
    ]
    if image_markdown:
        parts.append(image_markdown)
    elif screenshot_note:
        parts.append(f"_{screenshot_note}_")
    return "\n".join(parts).rstrip() + "\n"


def create_ticket(
    recorder,
    message: str,
    user,
    screenshot: tuple[bytes, str] | None,
    now: datetime | None = None,
) -> str | None:
    """Create the issue; return its ``web_url`` (None if not on the configured host)."""
    cfg = MonitorSettings.load()
    token = cfg.gitlab_token_plain()
    allow_http = settings.DEBUG
    if parse_project_url(cfg.gitlab_url, allow_http=allow_http) is None or not token:
        raise GitLabError("GitLab is not configured correctly")
    now = now or timezone.now()
    image_markdown = None
    note = None
    if screenshot is None:
        note = _("No screenshot attached.")
    else:
        data, content_type = screenshot
        ext = "jpg" if content_type == "image/jpeg" else "png"
        stamp = timezone.localtime(now, BERLIN).strftime("%Y%m%d-%H%M")
        filename = f"ansehbar-{recorder.stream_name}-{stamp}.{ext}"
        try:
            image_markdown = upload_file(
                cfg.gitlab_url,
                token,
                filename=filename,
                data=data,
                content_type=content_type,
                allow_http=allow_http,
            )
        except GitLabError as exc:
            logger.warning("Screenshot upload failed for recorder %s: %s", recorder.pk, exc)
            note = _("The screenshot upload to GitLab failed; no image attached.")
    title = build_title(recorder, message)
    description = build_description(recorder, message, user, now, image_markdown, note)
    try:
        issue = create_issue(
            cfg.gitlab_url,
            token,
            title=title,
            description=description,
            allow_http=allow_http,
        )
    except GitLabError as exc:
        logger.warning("GitLab issue failed for recorder %s: %s", recorder.pk, exc)
        raise
    if issue.web_url is None:
        # The issue exists; answering with an error would invite duplicates.
        logger.warning("GitLab returned no usable web_url for recorder %s", recorder.pk)
    return issue.web_url
