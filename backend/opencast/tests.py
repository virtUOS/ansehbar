# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from django.test import SimpleTestCase

from opencast.client import Agent, Event, OpencastClient, OpencastError

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
