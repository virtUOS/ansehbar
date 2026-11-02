# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Read-only client for the Opencast External API. No Django imports.

Only GET requests are ever sent; ansehBAR never writes to Opencast.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


class OpencastError(Exception):
    """Request or response problem. Never contains credentials."""


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
        except httpx.HTTPError as exc:
            raise OpencastError(f"{path}: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise OpencastError(f"{path}: HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise OpencastError(f"{path}: invalid JSON") from None
        if not isinstance(data, list):
            raise OpencastError(f"{path}: unexpected response shape")
        return data

    def _get_all(self, path: str, params: dict | None = None) -> list:
        items: list = []
        deadline = time.monotonic() + self.total_timeout
        for page in range(self.max_pages):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OpencastError(f"{path}: timeout")
            query = dict(params or {})
            query["limit"] = self.page_size
            query["offset"] = page * self.page_size
            chunk = self._get_page(path, query, min(self.timeout, remaining))
            items.extend(chunk)
            if len(chunk) < self.page_size:
                return items
        raise OpencastError(f"{path}: more than {self.max_pages} pages")

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
            scheduling = raw.get("scheduling")
            if not isinstance(scheduling, dict):
                continue
            identifier = raw.get("identifier")
            agent_id = scheduling.get("agent_id")
            ev_start = _parse_time(scheduling.get("start"))
            ev_end = _parse_time(scheduling.get("end"))
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
                )
            )
        return result
