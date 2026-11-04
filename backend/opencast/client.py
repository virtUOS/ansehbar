# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Read-only client for the Opencast External API. No Django imports.

Only GET requests are ever sent; ansehBAR never writes to Opencast.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx


class OpencastError(Exception):
    """Request or response problem. Never contains credentials.

    `kind` is one of: unreachable, auth, forbidden, timeout, server, invalid.
    (The monitor records "internal" for its own failures during a sync.)
    """

    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Agent:
    agent_id: str
    state: str
    updated_at: datetime | None


@dataclass(frozen=True)
class Event:
    identifier: str
    agent_id: str
    title: str
    series: str
    start: datetime
    end: datetime
    # Raw Opencast status, e.g. "EVENTS.EVENTS.STATUS.PROCESSED"; "" if absent.
    status: str = ""
    # Presenter names from Opencast, joined with ", "; "" if absent.
    presenters: str = ""


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_presenters(value) -> str:
    if not isinstance(value, list):
        return ""
    names = [v.strip() for v in value if isinstance(v, str)]
    return ", ".join(n for n in names if n)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OpencastClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        client: httpx.Client,
        timeout: float = 10.0,
        page_size: int = 100,
        max_pages: int = 50,
        total_timeout: float = 45.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = httpx.BasicAuth(user, password)
        self.client = client
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages
        # Budget for all pages of one listing, so a slow server cannot keep a
        # sync busy for max_pages * timeout.
        self.total_timeout = total_timeout

    def _get_page(self, path: str, params: dict, timeout: float) -> list:
        try:
            response = self.client.get(
                self.base_url + path,
                params=params,
                auth=self.auth,
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise OpencastError(f"{path}: {type(exc).__name__}", "timeout") from None
        except httpx.HTTPError as exc:
            raise OpencastError(f"{path}: {type(exc).__name__}", "unreachable") from None
        status = response.status_code
        if status == 401:
            raise OpencastError(f"{path}: HTTP 401", "auth")
        if status == 403:
            raise OpencastError(f"{path}: HTTP 403", "forbidden")
        if status >= 500:
            raise OpencastError(f"{path}: HTTP {status}", "server")
        # Opencast answers forbidden pages with an HTML page, sometimes with
        # HTTP 200 and a JSON content type: detect it before parsing.
        text = response.text
        if text.lstrip().startswith("<") or "Opencast :: Forbidden" in text:
            raise OpencastError(f"{path}: forbidden (HTML response)", "forbidden")
        if status != 200:
            raise OpencastError(f"{path}: HTTP {status}", "invalid")
        try:
            data = response.json()
        except ValueError:
            raise OpencastError(f"{path}: invalid JSON", "invalid") from None
        if not isinstance(data, list):
            raise OpencastError(f"{path}: unexpected response shape", "invalid")
        return data

    def _get_all(self, path: str, params: dict | None = None) -> list:
        items: list = []
        deadline = time.monotonic() + self.total_timeout
        for page in range(self.max_pages):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpencastError(f"{path}: timeout", "timeout")
            query = dict(params or {})
            query["limit"] = self.page_size
            query["offset"] = page * self.page_size
            chunk = self._get_page(path, query, min(self.timeout, remaining))
            items.extend(chunk)
            if len(chunk) < self.page_size:
                return items
        raise OpencastError(f"{path}: more than {self.max_pages} pages", "invalid")

    def agents(self) -> list[Agent]:
        result = []
        for raw in self._get_all("/api/agents"):
            if not isinstance(raw, dict):
                continue
            agent_id = raw.get("agent_id")
            if not agent_id or not isinstance(agent_id, str):
                continue
            result.append(
                Agent(
                    agent_id=agent_id,
                    state=str(raw.get("status") or ""),
                    updated_at=_parse_time(raw.get("update")),
                )
            )
        return result

    def scheduled_events(self, start: datetime, end: datetime) -> list[Event]:
        params = {
            "withscheduling": "true",
            "filter": f"start:{_format_time(start)}/{_format_time(end)}",
            "sort": "start_date:ASC",
        }
        result = []
        for raw in self._get_all("/api/events/", params):
            if not isinstance(raw, dict):
                continue
            identifier = raw.get("identifier")
            scheduling = raw.get("scheduling")
            agent_id = ev_start = ev_end = None
            if isinstance(scheduling, dict) and scheduling.get("agent_id"):
                agent_id = scheduling.get("agent_id")
                ev_start = _parse_time(scheduling.get("start"))
                ev_end = _parse_time(scheduling.get("end"))
            else:
                # Processed events may have lost their scheduling data: fall
                # back to the capture location and the Dublin Core times.
                location = raw.get("location")
                duration = raw.get("duration")
                ev_start = _parse_time(raw.get("start"))
                if (
                    isinstance(location, str)
                    and location
                    and ev_start
                    and isinstance(duration, (int, float))
                    and not isinstance(duration, bool)
                    and duration > 0
                ):
                    agent_id = location
                    ev_end = ev_start + timedelta(milliseconds=duration)
            if not (identifier and agent_id and ev_start and ev_end):
                continue
            result.append(
                Event(
                    identifier=identifier,
                    agent_id=agent_id,
                    title=str(raw.get("title") or ""),
                    series=str(raw.get("series") or ""),
                    start=ev_start,
                    end=ev_end,
                    status=str(raw.get("status") or ""),
                    presenters=_parse_presenters(raw.get("presenter")),
                )
            )
        return result
