# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Create GitLab issues for a recorder (status, Opencast details, screenshot).

Only ``POST .../uploads`` and ``POST .../issues`` are ever sent. Requests use
``follow_redirects=False`` and the token only travels to the configured host;
it never appears in exceptions, logs or responses.
"""

import logging
from datetime import datetime
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from opencast.models import ScheduledEvent
from recorders.models import MonitorSettings

logger = logging.getLogger(__name__)

TITLE_MAX = 255
TIMEOUT_SECONDS = 15
BERLIN = ZoneInfo("Europe/Berlin")


class GitLabError(Exception):
    """GitLab problem; the message never contains the token."""


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


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
    project = parts.path.strip("/").split("/-/", 1)[0].strip("/")
    if not project:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}", project


def safe_web_url(web_url: object, configured_url: str) -> str | None:
    """The issue link, only if scheme and host match the configured GitLab."""
    if not isinstance(web_url, str):
        return None
    try:
        got = urlsplit(web_url.strip())
        want = urlsplit(configured_url.strip())
        got.port, want.port  # noqa: B018 - validate
    except ValueError:
        return None
    if got.scheme.lower() not in ("http", "https") or not got.netloc:
        return None
    if got.scheme.lower() != want.scheme.lower():
        return None
    if got.netloc.lower() != want.netloc.lower():
        return None
    return web_url.strip()


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


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _post(client, url, token, **kwargs) -> dict:
    try:
        response = client.post(url, headers={"PRIVATE-TOKEN": token}, **kwargs)
    except httpx.HTTPError as exc:
        # Type only: the message could echo request details.
        raise GitLabError(f"GitLab unreachable ({type(exc).__name__})") from None
    if not 200 <= response.status_code < 300:
        raise GitLabError(f"GitLab answered HTTP {response.status_code}")
    return _json(response)


def _api(base: str, project: str, tail: str) -> str:
    return f"{base}/api/v4/projects/{quote(project, safe='')}/{tail}"


def upload_image(client, base, project, token, data, filename, content_type) -> str:
    body = _post(
        client,
        _api(base, project, "uploads"),
        token,
        files={"file": (filename, data, content_type)},
    )
    markdown = body.get("markdown")
    if not isinstance(markdown, str) or not markdown:
        raise GitLabError("GitLab upload returned no markdown")
    return markdown


def create_issue(client, base, project, token, title, description) -> dict:
    return _post(
        client,
        _api(base, project, "issues"),
        token,
        data={"title": title, "description": description},
    )


def create_ticket(
    recorder,
    message: str,
    user,
    screenshot: tuple[bytes, str] | None,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Create the issue and return its ``web_url``; raise GitLabError."""
    cfg = MonitorSettings.load()
    parsed = parse_project_url(cfg.gitlab_url)
    token = cfg.gitlab_token_plain()
    if parsed is None or not token:
        raise GitLabError("GitLab is not configured correctly")
    base, project = parsed
    now = now or timezone.now()
    own_client = client is None
    client = client or _client()
    try:
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
                image_markdown = upload_image(
                    client, base, project, token, data, filename, content_type
                )
            except GitLabError as exc:
                logger.warning("Screenshot upload failed for recorder %s: %s", recorder.pk, exc)
                note = _("The screenshot upload to GitLab failed; no image attached.")
        title = build_title(recorder, message)
        description = build_description(recorder, message, user, now, image_markdown, note)
        try:
            issue = create_issue(client, base, project, token, title, description)
        except GitLabError as exc:
            logger.warning("GitLab issue failed for recorder %s: %s", recorder.pk, exc)
            raise
        web_url = safe_web_url(issue.get("web_url"), cfg.gitlab_url)
        if web_url is None:
            logger.warning("GitLab returned no usable web_url for recorder %s", recorder.pk)
            raise GitLabError("GitLab returned no usable issue link")
        return web_url
    finally:
        if own_client:
            client.close()
