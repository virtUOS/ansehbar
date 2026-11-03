# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

import httpx
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from opencast import sync
from opencast.client import Agent, Event, OpencastClient, OpencastError
from opencast.models import IgnoredAgent, OpencastSyncState, ScheduledEvent
from recorders.models import Incident, Recorder

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


class ErrorKindTests(SimpleTestCase):
    def kind(self, handler, **kwargs):
        client, _ = make_client(handler, **kwargs)
        with self.assertRaises(OpencastError) as ctx:
            client.agents()
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertNotIn("opencast.example.org", str(ctx.exception))
        return ctx.exception.kind

    def test_html_forbidden_with_200_is_forbidden_error(self):
        body = (
            "<!DOCTYPE html>\n<html><head><title>Opencast :: Forbidden</title>"
            "</head><body>Forbidden</body></html>"
        )
        handler = lambda r: httpx.Response(  # noqa: E731
            200, text=body, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(self.kind(handler), "forbidden")

    def test_forbidden_text_without_markup_is_forbidden(self):
        handler = lambda r: httpx.Response(200, text="Opencast :: Forbidden")  # noqa: E731
        self.assertEqual(self.kind(handler), "forbidden")

    def test_http_403_is_forbidden(self):
        self.assertEqual(self.kind(lambda r: httpx.Response(403)), "forbidden")

    def test_http_401_is_auth(self):
        self.assertEqual(self.kind(lambda r: httpx.Response(401)), "auth")

    def test_http_503_is_server(self):
        self.assertEqual(self.kind(lambda r: httpx.Response(503)), "server")

    def test_connect_error_is_unreachable(self):
        def boom(request):
            raise httpx.ConnectError("refused", request=request)

        self.assertEqual(self.kind(boom), "unreachable")

    def test_request_timeout_is_timeout(self):
        def boom(request):
            raise httpx.ReadTimeout("slow", request=request)

        self.assertEqual(self.kind(boom), "timeout")

    def test_total_timeout_is_timeout(self):
        row = fixture("agents.json")[0]
        clock = [0.0]

        def slow(request):
            clock[0] += 20
            return json_response([row, row])

        with mock.patch("opencast.client.time.monotonic", lambda: clock[0]):
            self.assertEqual(self.kind(slow, page_size=2, total_timeout=45), "timeout")

    def test_invalid_json_is_invalid(self):
        self.assertEqual(self.kind(lambda r: httpx.Response(200, text="{")), "invalid")

    def test_wrong_shape_is_invalid(self):
        self.assertEqual(self.kind(lambda r: json_response({"a": 1})), "invalid")

    def test_max_pages_is_invalid(self):
        row = fixture("agents.json")[0]
        handler = lambda r: json_response([row, row])  # noqa: E731
        self.assertEqual(self.kind(handler, page_size=2, max_pages=2), "invalid")


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

    def test_event_status_parsed(self):
        raw = [
            {
                "identifier": "s1", "title": "T", "status": "EVENTS.EVENTS.STATUS.PROCESSED",
                "scheduling": {"agent_id": "a1", "start": "2026-11-01T08:00:00Z",
                               "end": "2026-11-01T09:00:00Z"},
            },
            {
                "identifier": "s2", "title": "T",
                "scheduling": {"agent_id": "a1", "start": "2026-11-01T08:00:00Z",
                               "end": "2026-11-01T09:00:00Z"},
            },
        ]
        client, _ = make_client(lambda r: json_response(raw))
        first, second = client.scheduled_events(*self.window())
        self.assertEqual(first.status, "EVENTS.EVENTS.STATUS.PROCESSED")
        self.assertEqual(second.status, "")

    def test_processed_event_without_scheduling_uses_location_and_duration(self):
        raw = [{
            "identifier": "p1", "title": "Done", "series": "S", "location": "cap-90-R12",
            "start": "2026-11-01T08:00:00Z", "duration": 5400000,
            "status": "EVENTS.EVENTS.STATUS.PROCESSED", "scheduling": {},
        }]
        client, _ = make_client(lambda r: json_response(raw))
        (event,) = client.scheduled_events(*self.window())
        self.assertEqual(event.agent_id, "cap-90-R12")
        self.assertEqual(event.start, datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(event.end, datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(event.status, "EVENTS.EVENTS.STATUS.PROCESSED")

    def test_event_without_scheduling_and_location_skipped(self):
        base = {"title": "T", "start": "2026-11-01T08:00:00Z", "duration": 1000,
                "scheduling": {}}
        raw = [
            {**base, "identifier": "u1", "location": ""},
            {**base, "identifier": "u2"},
            {**base, "identifier": "u3", "location": "a1", "duration": 0},
            {**base, "identifier": "u4", "location": "a1", "duration": None},
            {**base, "identifier": "u5", "location": "a1", "start": "bad"},
        ]
        client, _ = make_client(lambda r: json_response(raw))
        self.assertEqual(client.scheduled_events(*self.window()), [])


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
            raise OpencastError("/api/events/: HTTP 500", "server")
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
        sync.sync_events([a, b], ws, we, now=NOW)
        self.assertEqual(ScheduledEvent.objects.count(), 2)
        before = ScheduledEvent.objects.create(
            identifier="c",
            recorder=Recorder.objects.get(),
            start=ws - timedelta(hours=2),
            end=ws - timedelta(hours=1),
        )
        result = sync.sync_events([self.event("a", title="New")], ws, we, now=NOW)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(ScheduledEvent.objects.get(identifier="a").title, "New")
        self.assertFalse(ScheduledEvent.objects.filter(identifier="b").exists())
        self.assertTrue(ScheduledEvent.objects.filter(pk=before.pk).exists())

    def test_event_for_unknown_agent_is_unmatched(self):
        ws, we = sync.sync_window(NOW, 7)
        result = sync.sync_events([self.event("a", agent_id="nobody")], ws, we, now=NOW)
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
            sync.sync_events([self.event(long_id), self.event("ok")], ws, we, now=NOW)
            sync.sync_events([self.event(long_id), self.event("ok")], ws, we, now=NOW)
        self.assertEqual(
            list(ScheduledEvent.objects.values_list("identifier", flat=True)), ["ok"]
        )
        self.assertEqual(len(logs.records), 1)

    def test_empty_event_list_keeps_stored_events_with_warning(self):
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        ended = self.event("ended", start=utc(2026, 11, 3, 7, 0))  # 07:00-09:00
        past = self.event("past", start=utc(2026, 10, 30, 8, 0))  # lookback part
        sync.sync_events([self.event("a"), self.event("b"), ended, past], ws, we, now=NOW)
        incident = Incident.objects.create(
            recorder=rec, event=ScheduledEvent.objects.get(identifier="ended"),
            kind=Incident.STREAM_MISSING, started_at=utc(2026, 11, 3, 7, 10),
            ended_at=utc(2026, 11, 3, 7, 20),
        )
        with self.assertLogs("opencast.sync", level="WARNING") as logs:
            result = sync.sync_events([], ws, we, now=NOW)
        self.assertEqual(result.deleted, 0)
        self.assertEqual(ScheduledEvent.objects.count(), 4)
        incident.refresh_from_db()
        self.assertEqual(incident.event.identifier, "ended")
        self.assertIn("kept 3", logs.output[0])

    def test_lookback_events_missing_from_partial_sync_stay(self):
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        # Local midnight of yesterday (2026-11-02 00:00 CET) splits the window:
        # events before it that have ended are only ever upserted.
        past = self.event("past", start=utc(2026, 10, 30, 8, 0))
        yesterday = self.event("yesterday", start=utc(2026, 11, 2, 8, 0))
        future = self.event("future")
        sync.sync_events([past, yesterday, future], ws, we, now=NOW)
        incident = Incident.objects.create(
            recorder=rec, event=ScheduledEvent.objects.get(identifier="past"),
            kind=Incident.STREAM_MISSING, started_at=utc(2026, 10, 30, 8, 10),
            ended_at=utc(2026, 10, 30, 8, 20),
        )
        result = sync.sync_events([self.event("other")], ws, we, now=NOW)
        self.assertEqual(result.deleted, 2)
        self.assertEqual(
            set(ScheduledEvent.objects.values_list("identifier", flat=True)),
            {"past", "other"},
        )
        incident.refresh_from_db()
        self.assertEqual(incident.event.identifier, "past")

    def test_fallback_event_syncs_end_to_end_and_stays_attached(self):
        rec = Recorder.objects.create(
            stream_name="cap-90-R12", room_name="R12", agent_id="cap-90-R12"
        )
        raw = [{
            "identifier": "p1", "title": "Done", "series": "S", "location": "cap-90-R12",
            "start": "2026-11-01T08:00:00Z", "duration": 5400000,
            "status": "EVENTS.EVENTS.STATUS.PROCESSED", "scheduling": {},
        }]
        oc, _ = make_client(lambda r: json_response(raw))
        ws, we = sync.sync_window(NOW, 7)
        result = sync.sync_events(oc.scheduled_events(ws, we), ws, we, now=NOW)
        self.assertEqual(result.upserted, 1)
        event = ScheduledEvent.objects.get(identifier="p1")
        self.assertEqual(event.recorder, rec)
        self.assertEqual(event.end, utc(2026, 11, 1, 9, 30))
        self.assertEqual(event.opencast_status, "EVENTS.EVENTS.STATUS.PROCESSED")
        incident = Incident.objects.create(
            recorder=rec, event=event, kind=Incident.STREAM_MISSING,
            started_at=utc(2026, 11, 1, 8, 10), ended_at=utc(2026, 11, 1, 8, 20),
        )
        # Opencast no longer lists it (e.g. archived): it stays, so does the link.
        sync.sync_events([self.event("other", agent_id="cap-90-R12")], ws, we, now=NOW)
        incident.refresh_from_db()
        self.assertEqual(incident.event, event)

    def test_unlinked_agent_events_are_removed(self):
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        sync.sync_events([self.event("a")], ws, we, now=NOW)
        self.assertEqual(ScheduledEvent.objects.get().recorder, rec)
        rec.agent_id = None
        rec.save()
        result = sync.sync_events([self.event("a")], ws, we, now=NOW)
        self.assertEqual(result.unmatched, 1)
        self.assertEqual(result.deleted, 1)
        self.assertEqual(ScheduledEvent.objects.count(), 0)

    def test_sync_window_local_midnight(self):
        ws, we = sync.sync_window(utc(2026, 11, 1, 23, 30), 7, lookback_days=1)
        self.assertEqual(ws, utc(2026, 10, 31, 23, 0))
        self.assertEqual(we, utc(2026, 11, 9, 23, 0))

    def test_sync_window_lookback(self):
        ws, we = sync.sync_window(utc(2026, 11, 1, 23, 30), 7)
        self.assertEqual(ws, utc(2026, 10, 25, 23, 0))
        self.assertEqual(we, utc(2026, 11, 9, 23, 0))
        ws, _ = sync.sync_window(utc(2026, 11, 1, 23, 30), 7, lookback_days=3)
        self.assertEqual(ws, utc(2026, 10, 29, 23, 0))

    def test_sync_stores_opencast_status(self):
        Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        ev = self.event("a")
        ev = Event(
            ev.identifier, ev.agent_id, ev.title, ev.series, ev.start, ev.end,
            status="EVENTS.EVENTS.STATUS.PROCESSED",
        )
        sync.sync_events([ev], ws, we, now=NOW)
        self.assertEqual(
            ScheduledEvent.objects.get(identifier="a").opencast_status,
            "EVENTS.EVENTS.STATUS.PROCESSED",
        )
        sync.sync_events([self.event("a")], ws, we, now=NOW)
        self.assertEqual(ScheduledEvent.objects.get(identifier="a").opencast_status, "")

    def test_sync_marks_delivered_events_seen(self):
        Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="rec-hall"
        )
        ws, we = sync.sync_window(NOW, 7)
        sync.sync_events([self.event("a")], ws, we, now=NOW)
        self.assertEqual(ScheduledEvent.objects.get(identifier="a").seen_at, NOW)

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

    def test_sync_sets_no_events_hint(self):
        client = FakeClient(agents=[self.agent("rec-hall"), self.agent("rec-b")])
        sync.run_opencast_sync(client, NOW, 7)
        state = OpencastSyncState.load()
        self.assertEqual(state.last_success_at, NOW)
        self.assertEqual(state.last_error, "")
        self.assertEqual(state.last_error_kind, "no_events")
        self.assertEqual(Recorder.objects.count(), 2)

    def test_sync_without_agents_and_events_has_no_hint(self):
        sync.run_opencast_sync(FakeClient(), NOW, 7)
        self.assertEqual(OpencastSyncState.load().last_error_kind, "")

    def test_sync_success_clears_error_kind(self):
        state = OpencastSyncState.load()
        state.last_error_kind = "auth"
        state.save()
        client = FakeClient(agents=[self.agent("rec-hall")], events=[self.event("a")])
        sync.run_opencast_sync(client, NOW, 7)
        self.assertEqual(OpencastSyncState.load().last_error_kind, "")

    def test_sync_error_kind_recorded(self):
        class Failing(FakeClient):
            def agents(self):
                raise OpencastError("/api/agents: HTTP 401", "auth")

        sync.run_opencast_sync(Failing(), NOW, 7)
        state = OpencastSyncState.load()
        self.assertEqual(state.last_error_kind, "auth")
        self.assertTrue(state.last_error)
        self.assertEqual(Recorder.objects.count(), 0)

    def _request_during(self, fail):
        class Racing(FakeClient):
            def agents(inner):
                state = OpencastSyncState.load()
                state.requested_at = NOW + timedelta(seconds=1)
                state.save(update_fields=["requested_at"])
                if fail:
                    raise OpencastError("/api/agents: HTTP 401", "auth")
                return []

        sync.run_opencast_sync(Racing(), NOW, 7)
        self.assertTrue(OpencastSyncState.load().sync_requested)

    def test_request_during_successful_sync_is_kept(self):
        self._request_during(fail=False)

    def test_request_during_failed_sync_is_kept(self):
        self._request_during(fail=True)


User = get_user_model()


class SyncRequestApiTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username="m", is_superuser=True))

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_sync_request_endpoint(self):
        response = self.client.post("/api/opencast/sync/")
        self.assertEqual(response.status_code, 202)
        state = OpencastSyncState.load()
        self.assertIsNotNone(state.requested_at)
        self.assertEqual(
            datetime.fromisoformat(response.json()["requested_at"].replace("Z", "+00:00")),
            state.requested_at,
        )

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_repeated_sync_request_keeps_pending_request(self):
        first = self.client.post("/api/opencast/sync/").json()["requested_at"]
        second = self.client.post("/api/opencast/sync/")
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["requested_at"], first)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_sync_request_right_after_an_attempt_is_ignored(self):
        state = OpencastSyncState.load()
        state.last_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=3)
        state.save()
        self.assertEqual(self.client.post("/api/opencast/sync/").status_code, 202)
        self.assertIsNone(OpencastSyncState.load().requested_at)
        state.last_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        state.save()
        self.client.post("/api/opencast/sync/")
        self.assertIsNotNone(OpencastSyncState.load().requested_at)

    @override_settings(OPENCAST_URL="")
    def test_sync_request_without_opencast_is_409(self):
        response = self.client.post("/api/opencast/sync/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Opencast is not configured."})
        self.assertIsNone(OpencastSyncState.load().requested_at)

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=False)
    def test_sync_request_with_plain_http_without_debug_is_409(self):
        response = self.client.post("/api/opencast/sync/")
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(OpencastSyncState.load().requested_at)

    @override_settings(OPENCAST_URL="http://opencast.example.org", DEBUG=True)
    def test_sync_request_with_plain_http_in_debug_is_accepted(self):
        self.assertEqual(self.client.post("/api/opencast/sync/").status_code, 202)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_sync_request_requires_access(self):
        self.client.force_login(User.objects.create_user(username="outsider"))
        self.assertEqual(self.client.post("/api/opencast/sync/").status_code, 403)
        self.assertIsNone(OpencastSyncState.load().requested_at)

    @override_settings(OPENCAST_URL="https://opencast.example.org")
    def test_sync_request_rejects_get(self):
        self.assertEqual(self.client.get("/api/opencast/sync/").status_code, 405)


class IgnoredAgentTests(TestCase):
    def setUp(self):
        sync._logged.clear()
        self.client.force_login(User.objects.create_user(username="m", is_superuser=True))

    def test_ignored_agent_is_skipped_silently(self):
        IgnoredAgent.objects.create(agent_id="cap-90-R12")
        Recorder.objects.all().delete()
        with self.assertNoLogs("opencast.sync", level="WARNING"):
            result = sync.sync_agents([Agent("cap-90-R12", "idle", NOW)], NOW)
        self.assertEqual((result.created, result.linked, result.skipped), (0, 0, []))
        self.assertFalse(Recorder.objects.exists())

    def test_ignored_agent_is_not_linked_to_stream_name(self):
        IgnoredAgent.objects.create(agent_id="rec-hall")
        rec = Recorder.objects.create(stream_name="rec-hall", room_name="Hall")
        sync.sync_agents([Agent("rec-hall", "idle", NOW)], NOW)
        rec.refresh_from_db()
        self.assertIsNone(rec.agent_id)

    def test_ignored_agent_still_updates_linked_recorder(self):
        # Linked by hand to an ignored agent: state and "gone" still apply.
        IgnoredAgent.objects.create(agent_id="cap-90-R12")
        Recorder.objects.all().delete()
        rec = Recorder.objects.create(
            stream_name="rec-hall", room_name="Hall", agent_id="cap-90-R12"
        )
        sync.sync_agents([Agent("cap-90-R12", "capturing", NOW)], NOW)
        rec.status.refresh_from_db()
        self.assertEqual(rec.status.agent_state, "capturing")
        self.assertEqual(rec.status.agent_updated_at, NOW)
        result = sync.sync_agents([], NOW)
        self.assertEqual(result.gone, 1)
        rec.status.refresh_from_db()
        self.assertEqual(rec.status.agent_state, "unknown")

    def test_agent_ignored_during_sync_is_not_created(self):
        # The recorder is deleted (and its agent ignored) after the ignore
        # list was read: the re-check before creating honours it.
        Recorder.objects.all().delete()
        real_filter = Recorder.objects.filter

        def filter_then_ignore(*args, **kwargs):
            if "stream_name" in kwargs:
                IgnoredAgent.objects.get_or_create(agent_id="cap-90-R12")
            return real_filter(*args, **kwargs)

        with mock.patch.object(Recorder.objects, "filter", filter_then_ignore):
            result = sync.sync_agents([Agent("cap-90-R12", "idle", NOW)], NOW)
        self.assertEqual(result.created, 0)
        self.assertFalse(Recorder.objects.exists())

    def test_events_of_ignored_agent_skipped_silently(self):
        IgnoredAgent.objects.create(agent_id="cap-90-R12")
        start = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
        event = Event("e1", "cap-90-R12", "T", "S", start, start + timedelta(hours=1))
        ws, we = sync.sync_window(NOW, 7)
        with self.assertNoLogs("opencast.sync", level="WARNING"):
            result = sync.sync_events([event], ws, we, {"cap-90-R12"}, now=NOW)
        self.assertEqual(result.unmatched, 0)
        self.assertFalse(ScheduledEvent.objects.exists())

    def test_run_sync_passes_ignored_agents_to_events(self):
        IgnoredAgent.objects.create(agent_id="cap-90-R12")
        Recorder.objects.all().delete()
        start = datetime(2026, 11, 4, 8, 0, tzinfo=timezone.utc)
        event = Event("e1", "cap-90-R12", "T", "S", start, start + timedelta(hours=1))
        client = FakeClient([Agent("cap-90-R12", "idle", NOW)], [event])
        with self.assertNoLogs("opencast.sync", level="WARNING"):
            sync.run_opencast_sync(client, NOW, 7)
        self.assertFalse(ScheduledEvent.objects.exists())

    def test_unignore_lets_agent_return(self):
        ignored = IgnoredAgent.objects.create(agent_id="cap-90-R12", created_by="X")
        listing = self.client.get("/api/ignored-agents/").json()
        self.assertEqual(listing[0]["agent_id"], "cap-90-R12")
        self.assertEqual(
            set(listing[0]), {"id", "agent_id", "created_at", "created_by"}
        )
        response = self.client.delete(f"/api/ignored-agents/{ignored.pk}/")
        self.assertEqual(response.status_code, 204)
        sync.sync_agents([Agent("cap-90-R12", "idle", NOW)], NOW)
        self.assertTrue(Recorder.objects.get(agent_id="cap-90-R12").needs_review)

    def test_ignored_agents_requires_access(self):
        ignored = IgnoredAgent.objects.create(agent_id="a")
        self.client.force_login(User.objects.create_user(username="outsider"))
        self.assertEqual(self.client.get("/api/ignored-agents/").status_code, 403)
        self.assertEqual(
            self.client.delete(f"/api/ignored-agents/{ignored.pk}/").status_code, 403
        )
        self.assertTrue(IgnoredAgent.objects.filter(pk=ignored.pk).exists())
