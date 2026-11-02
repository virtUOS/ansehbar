# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Mirror Opencast agents and scheduled events into the database.

Read-only towards Opencast. A sync run fetches everything first and applies
it in one transaction, so a failed request never leaves half-applied data.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from opencast.client import Agent, Event, OpencastClient, OpencastError
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from recorders.models import Recorder, RecorderStatus
from recorders.validators import validate_stream_name

logger = logging.getLogger(__name__)

# (kind, agent_id) pairs already warned about in this process.
_logged: set[tuple[str, str]] = set()


def _warn_once(kind: str, agent_id: str, message: str) -> None:
    if (kind, agent_id) in _logged:
        return
    _logged.add((kind, agent_id))
    logger.warning(message, agent_id)


@dataclass
class AgentSyncResult:
    created: int = 0
    linked: int = 0
    skipped: list[str] = field(default_factory=list)
    gone: int = 0


@dataclass
class EventSyncResult:
    upserted: int = 0
    deleted: int = 0
    unmatched: int = 0


AGENT_STATE_MAX = RecorderStatus._meta.get_field("agent_state").max_length
EVENT_ID_MAX = ScheduledEvent._meta.get_field("identifier").max_length


def _set_status(recorder: Recorder, agent: Agent) -> None:
    RecorderStatus.objects.update_or_create(
        recorder=recorder,
        defaults={
            "agent_state": agent.state[:AGENT_STATE_MAX],
            "agent_updated_at": agent.updated_at,
        },
    )


def sync_agents(agents: list[Agent], now: datetime) -> AgentSyncResult:
    result = AgentSyncResult()
    max_len = Recorder._meta.get_field("agent_id").max_length
    seen: set[str] = set()
    ignored = set(IgnoredAgent.objects.values_list("agent_id", flat=True))
    for agent in agents:
        seen.add(agent.agent_id)
        if agent.agent_id in ignored:
            continue
        recorder = Recorder.objects.filter(agent_id=agent.agent_id).first()
        if recorder is None:
            try:
                validate_stream_name(agent.agent_id)
                if len(agent.agent_id) > max_len:
                    raise ValidationError("too long")
            except ValidationError:
                result.skipped.append(agent.agent_id)
                _warn_once(
                    "agent", agent.agent_id,
                    "Opencast agent %r skipped: not a valid stream name",
                )
                continue
            recorder = Recorder.objects.filter(stream_name=agent.agent_id).first()
            if recorder is None:
                recorder = Recorder.objects.create(
                    stream_name=agent.agent_id,
                    agent_id=agent.agent_id,
                    room_name="",
                    active=True,
                    needs_review=True,
                )
                result.created += 1
            elif recorder.agent_id is None:
                recorder.agent_id = agent.agent_id
                recorder.save()
                result.linked += 1
            else:
                result.skipped.append(agent.agent_id)
                _warn_once(
                    "agent", agent.agent_id,
                    "Opencast agent %r skipped: its stream name belongs to "
                    "a recorder linked to another agent",
                )
                continue
        _set_status(recorder, agent)

    for recorder in Recorder.objects.filter(agent_id__isnull=False).exclude(
        agent_id__in=seen
    ):
        RecorderStatus.objects.update_or_create(
            recorder=recorder, defaults={"agent_state": "unknown"}
        )
        result.gone += 1
    return result


def sync_events(
    events: list[Event], window_start: datetime, window_end: datetime
) -> EventSyncResult:
    result = EventSyncResult()
    recorders = {
        r.agent_id: r for r in Recorder.objects.filter(agent_id__isnull=False)
    }
    fetched: set[str] = set()
    for event in events:
        if len(event.identifier) > EVENT_ID_MAX:
            _warn_once(
                "event-id", event.identifier,
                "Opencast event %r skipped: identifier too long",
            )
            continue
        recorder = recorders.get(event.agent_id)
        if recorder is None:
            result.unmatched += 1
            _warn_once(
                "event", event.agent_id,
                "Opencast events for unknown agent %r ignored",
            )
            continue
        ScheduledEvent.objects.update_or_create(
            identifier=event.identifier,
            defaults={
                "recorder": recorder,
                "title": event.title[:300],
                "series": event.series[:300],
                "start": event.start,
                "end": event.end,
            },
        )
        # Only stored events count as fetched: events of an agent that no
        # longer maps to a recorder are removed from their old recorder below.
        fetched.add(event.identifier)
        result.upserted += 1
    stale = ScheduledEvent.objects.filter(
        start__gte=window_start, start__lt=window_end
    ).exclude(identifier__in=fetched)
    result.deleted = stale.count()
    stale.delete()
    if not events and result.deleted:
        logger.warning(
            "Opencast returned no events in the sync window; deleted %d stored "
            "events (check the Opencast user's access rights)",
            result.deleted,
        )
    return result


def sync_window(now: datetime, lookahead_days: int) -> tuple[datetime, datetime]:
    """Local midnight yesterday up to local midnight after the lookahead."""
    today = timezone.localtime(now).date()
    return (
        _local_midnight(today - timedelta(days=1)),
        _local_midnight(today + timedelta(days=lookahead_days + 1)),
    )


def _local_midnight(day) -> datetime:
    return timezone.make_aware(datetime(day.year, day.month, day.day))


def run_opencast_sync(
    client: OpencastClient, now: datetime, lookahead_days: int
) -> None:
    state = OpencastSyncState.load()
    state.last_attempt_at = now
    window_start, window_end = sync_window(now, lookahead_days)
    try:
        agents = client.agents()
        events = client.scheduled_events(window_start, window_end)
    except OpencastError as exc:
        state.last_error = str(exc)[:300]
        state.last_error_kind = exc.kind
        # update_fields: never overwrite requested_at set by a concurrent request.
        state.save(update_fields=["last_attempt_at", "last_error", "last_error_kind"])
        logger.warning("Opencast sync failed: %s", exc)
        return
    with transaction.atomic():
        sync_agents(agents, now)
        sync_events(events, window_start, window_end)
        state.last_success_at = now
        state.last_error = ""
        state.last_error_kind = "no_events" if agents and not events else ""
        state.save(
            update_fields=[
                "last_attempt_at", "last_success_at", "last_error", "last_error_kind",
            ]
        )
