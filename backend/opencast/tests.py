# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

import httpx
from django.test import SimpleTestCase, TestCase

from opencast import sync
from opencast.client import Agent, Event, OpencastClient, OpencastError
from opencast.models import OpencastSyncState, ScheduledEvent
from recorders.models import Recorder

FIXTURES = Path(__file__).parent / "fixtures"
PASSWORD = "s3cret-pw"
BASE = "https://opencast.example.org"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def make_client(handler, **kwargs):
    requests = []

    def wrapped(request):
        requests.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(wrapped))
    client = OpencastClient(BASE, "user", PASSWORD, http, **kwargs)
    return client, requests


def json_response(data):
    return httpx.Response(200, json=data)


class AgentsTests(SimpleTestCase):
    def test_agents_parses_state_and_update(self):
        client, _ = make_client(lambda r: json_response(fixture("agents.json")))
        agents = client.agents()
        self.assertEqual([a.agent_id for a in agents], ["cap-90-R12", "rec-hall", "Rec-Annex"])
        self.assertIsInstance(agents[0], Agent)
        self.assertEqual(agents[1].state, "capturing")
        self.assertEqual(agents[0].updated_at, datetime(2026, 11, 1, 19, 33, tzinfo=timezone.utc))
        self.assertIsNotNone(agents[0].updated_at.utcoffset())

    def test_agents_paginates(self):
        data = fixture("agents.json")

        def handler(request):
            offset = int(request.url.params["offset"])
            return json_response(data[offset : offset + 2])

        client, requests = make_client(handler, page_size=2)
        self.assertEqual(len(client.agents()), 3)
        offsets = [r.url.params["offset"] for r in requests]
        self.assertEqual(offsets, ["0", "2"])
        self.assertEqual(requests[0].url.params["limit"], "2")

    def test_error_on_http_500_page_two(self):
        data = fixture("agents.json")

        def handler(request):
            if request.url.params["offset"] == "0":
                return json_response(data[:2])
            return httpx.Response(500)

        client, _ = make_client(handler, page_size=2)
        with self.assertRaises(OpencastError) as ctx:
            client.agents()
        self.assertIn("500", str(ctx.exception))
        self.assertIn("/api/agents", str(ctx.exception))

    def test_error_on_network_and_invalid_json(self):
        def boom(request):
            raise httpx.ConnectError("refused", request=request)

        client, _ = make_client(boom)
        with self.assertRaises(OpencastError) as ctx:
            client.agents()
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertIn("ConnectError", str(ctx.exception))

        client, _ = make_client(lambda r: httpx.Response(200, text="<html>"))
        with self.assertRaises(OpencastError) as ctx:
            client.agents()
        self.assertNotIn(PASSWORD, str(ctx.exception))

    def test_error_when_max_pages_exceeded(self):
        row = fixture("agents.json")[0]
        client, requests = make_client(
            lambda r: json_response([row, row]), page_size=2, max_pages=3
        )
        with self.assertRaises(OpencastError):
            client.agents()
        self.assertEqual(len(requests), 3)

    def test_error_when_total_timeout_exceeded(self):
        row = fixture("agents.json")[0]
        clock = [0.0]

        def slow(request):
            clock[0] += 20  # every page takes 20 s
            return json_response([row, row])

        client, requests = make_client(slow, page_size=2, total_timeout=45)
        with mock.patch("opencast.client.time.monotonic", lambda: clock[0]), \
                self.assertRaises(OpencastError) as ctx:
            client.agents()
        self.assertEqual(str(ctx.exception), "/api/agents: timeout")
        self.assertEqual(len(requests), 3)
        # The last request only gets the remaining budget.
        self.assertEqual(requests[2].extensions["timeout"]["read"], 5)

    def test_basic_auth_and_accept_json(self):
        client, requests = make_client(lambda r: json_response([]))
        client.agents()
        self.assertTrue(requests[0].headers["Authorization"].startswith("Basic "))
        self.assertEqual(requests[0].headers["Accept"], "application/json")

    def test_only_get_requests(self):
        client, requests = make_client(lambda r: json_response([]))
        client.agents()
        client.scheduled_events(
            datetime(2026, 11, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 2, tzinfo=timezone.utc),
        )
        self.assertTrue(requests)
        self.assertEqual({r.method for r in requests}, {"GET"})


class EventsTests(SimpleTestCase):
    def window(self):
        return (
            datetime(2026, 11, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 2, tzinfo=timezone.utc),
        )

    def test_events_request_uses_scheduling_and_window(self):
        client, requests = make_client(lambda r: json_response([]))
        client.scheduled_events(*self.window())
        params = parse_qs(requests[0].url.query.decode())
        self.assertEqual(params["withscheduling"], ["true"])
        self.assertEqual(params["filter"], ["start:2026-11-01T00:00:00Z/2026-11-02T00:00:00Z"])
        self.assertEqual(params["sort"], ["start_date:ASC"])
        self.assertEqual(requests[0].url.path, "/api/events/")

    def test_events_skips_unscheduled_and_incomplete(self):
        client, _ = make_client(lambda r: json_response(fixture("events.json")))
        events = client.scheduled_events(*self.window())
        self.assertEqual([e.identifier for e in events], ["evt-0001", "evt-0002"])
        first, second = events
        self.assertIsInstance(first, Event)
        self.assertEqual(first.agent_id, "cap-90-R12")
        self.assertEqual(first.title, "Lecture A")
        self.assertEqual(first.series, "Series One")
        self.assertEqual(first.start, datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc))
        self.assertEqual(first.end, datetime(2026, 11, 1, 21, 0, tzinfo=timezone.utc))
        self.assertEqual(second.agent_id, "rec-hall")
        self.assertEqual(second.start, datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, agents=(), events=(), fail_events=False):
        self._agents = list(agents)
        self._events = list(events)
        self.fail_events = fail_events

    def agents(self):
        return self._agents

    def scheduled_events(self, start, end):
        if self.fail_events:
            raise OpencastError("/api/events/: HTTP 500")
        return self._events


NOW = utc(2026, 11, 3, 10, 0)


class SyncTests(TestCase):
    def setUp(self):
        sync._logged.clear()

    def agent(self, agent_id="cap-90-R12", state="idle"):
        return Agent(agent_id, state, NOW)

    def event(self, identifier, agent_id="rec-hall", title="T", start=None):
        start = start or utc(2026, 11, 4, 8, 0)
        return Event(identifier, agent_id, title, "S", start, start.replace(hour=9))

    def test_new_agent_creates_review_recorder(self):
        result = sync.sync_agents([self.agent()], NOW)
        self.assertEqual(result.created, 1)
        rec = Recorder.objects.get(agent_id="cap-90-R12")
        self.assertEqual(rec.stream_name, "cap-90-R12")
        self.assertEqual(rec.room_name, "")
        self.assertTrue(rec.active)
        self.assertTrue(rec.needs_review)
        self.assertEqual(rec.status.agent_state, "idle")
        self.assertEqual(rec.status.agent_updated_at, NOW)

    def test_agent_links_existing_recorder_by_stream_name(self):
        Recorder.objects.create(stream_name="rec-hall", room_name="Hall")
        result = sync.sync_agents([self.agent("rec-hall", "capturing")], NOW)
        self.assertEqual(result.linked, 1)
        self.assertEqual(result.created, 0)
        self.assertEqual(Recorder.objects.count(), 1)
        rec = Recorder.objects.get()
        self.assertEqual(rec.agent_id, "rec-hall")
        self.assertFalse(rec.needs_review)
        self.assertEqual(rec.status.agent_state, "capturing")

    def test_agent_with_invalid_stream_name_is_skipped(self):
        result = sync.sync_agents([self.agent("Hall 1")], NOW)
        self.assertEqual(result.skipped, ["Hall 1"])
        self.assertEqual(Recorder.objects.count(), 0)

    def test_agent_stream_name_taken_by_other_agent_is_skipped(self):
        Recorder.objects.create(stream_name="x", room_name="X", agent_id="y")
        result = sync.sync_agents([self.agent("x")], NOW)
        self.assertEqual(result.skipped, ["x"])
        self.assertEqual(Recorder.objects.count(), 1)

    def test_missing_agent_becomes_unknown(self):
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        rec.status.agent_state = "idle"
        rec.status.save()
        result = sync.sync_agents([], NOW)
        self.assertEqual(result.gone, 1)
        rec.refresh_from_db()
        self.assertEqual(rec.status.agent_state, "unknown")
        self.assertTrue(rec.active)

    def test_events_upsert_and_delete_cancelled_in_window(self):
        Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        a = self.event("a", title="Old")
        b = self.event("b", start=utc(2026, 11, 5, 8, 0))
        sync.sync_events([a, b], ws, we)
        self.assertEqual(ScheduledEvent.objects.count(), 2)
        before = ScheduledEvent.objects.create(
            identifier="c",
            recorder=Recorder.objects.get(),
            start=ws - timedelta(hours=2),
            end=ws - timedelta(hours=1),
        )
        result = sync.sync_events([self.event("a", title="New")], ws, we)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(ScheduledEvent.objects.get(identifier="a").title, "New")
        self.assertFalse(ScheduledEvent.objects.filter(identifier="b").exists())
        self.assertTrue(ScheduledEvent.objects.filter(pk=before.pk).exists())

    def test_event_for_unknown_agent_is_unmatched(self):
        ws, we = sync.sync_window(NOW, 7)
        result = sync.sync_events([self.event("a", agent_id="nobody")], ws, we)
        self.assertEqual(result.unmatched, 1)
        self.assertEqual(ScheduledEvent.objects.count(), 0)

    def test_long_agent_state_is_truncated(self):
        sync.sync_agents([self.agent(state="x" * 50)], NOW)
        rec = Recorder.objects.get(agent_id="cap-90-R12")
        self.assertEqual(rec.status.agent_state, "x" * 20)

    def test_event_with_too_long_identifier_is_skipped(self):
        Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        long_id = "e" * 129
        with self.assertLogs("opencast.sync", level="WARNING") as logs:
            sync.sync_events([self.event(long_id), self.event("ok")], ws, we)
            sync.sync_events([self.event(long_id), self.event("ok")], ws, we)
        self.assertEqual(
            list(ScheduledEvent.objects.values_list("identifier", flat=True)), ["ok"]
        )
        self.assertEqual(len(logs.records), 1)

    def test_empty_event_list_deletes_with_warning(self):
        Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        sync.sync_events([self.event("a"), self.event("b")], ws, we)
        with self.assertLogs("opencast.sync", level="WARNING") as logs:
            result = sync.sync_events([], ws, we)
        self.assertEqual(result.deleted, 2)
        self.assertEqual(ScheduledEvent.objects.count(), 0)
        self.assertIn("deleted 2", logs.output[0])

    def test_unlinked_agent_events_are_removed(self):
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        sync.sync_events([self.event("a")], ws, we)
        self.assertEqual(ScheduledEvent.objects.get().recorder, rec)
        rec.agent_id = None
        rec.save()
        result = sync.sync_events([self.event("a")], ws, we)
        self.assertEqual(result.unmatched, 1)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(ScheduledEvent.objects.count(), 0)

    def test_sync_window_local_midnight(self):
        ws, we = sync.sync_window(utc(2026, 11, 1, 23, 30), 7)
        self.assertEqual(ws, utc(2026, 10, 31, 23, 0))
        self.assertEqual(we, utc(2026, 11, 9, 23, 0))

    def test_run_sync_applies_nothing_on_error(self):
        client = FakeClient(agents=[self.agent()], fail_events=True)
        sync.run_opencast_sync(client, NOW, 7)
        self.assertEqual(Recorder.objects.count(), 0)
        state = OpencastSyncState.load()
        self.assertTrue(state.last_error)
        self.assertEqual(state.last_attempt_at, NOW)
        self.assertIsNone(state.last_success_at)

    def test_run_sync_success_records_state(self):
        client = FakeClient(
            agents=[self.agent("rec-hall")], events=[self.event("a")]
        )
        sync.run_opencast_sync(client, NOW, 7)
        state = OpencastSyncState.load()
        self.assertEqual(state.last_success_at, NOW)
        self.assertEqual(state.last_error, "")
        self.assertEqual(ScheduledEvent.objects.count(), 1)
