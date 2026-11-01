# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import unittest
from datetime import datetime, timedelta, timezone

import httpx

from streams.hls import parse_master, parse_media
from streams.sources import HlsStreamSource, LiveState, Probe, evaluate

MASTER = (
    "#EXTM3U\n#EXT-X-VERSION:3\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=1280000,CODECS=\"avc1.77.30,mp4a.40.2\","
    "RESOLUTION=1280x720\nchunklist_w123.m3u8\n"
)
MEDIA = (
    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n"
    "#EXT-X-MEDIA-SEQUENCE:42\n#EXTINF:10.0,\nmedia_w123_42.ts\n"
)
TEMPLATE = "https://live.example/live/{stream}/playlist.m3u8"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def source(handler):
    # Same redirect policy as run_monitor's client.
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return HlsStreamSource(TEMPLATE, client)


class ParseTests(unittest.TestCase):
    def test_parse_master_returns_variant_uris(self):
        self.assertEqual(parse_master(MASTER), ["chunklist_w123.m3u8"])

    def test_parse_master_of_media_playlist_is_empty(self):
        self.assertEqual(parse_master(MEDIA), [])

    def test_parse_media_reads_sequence_and_target(self):
        self.assertEqual(parse_media(MEDIA), (42, 10.0))

    def test_parse_media_missing_tags(self):
        self.assertEqual(parse_media("#EXTM3U\n"), (None, None))


class ProbeTests(unittest.TestCase):
    def test_playback_url_keeps_case(self):
        src = source(lambda r: httpx.Response(404))
        self.assertEqual(
            src.playback_url("cap-90-R12"),
            "https://live.example/live/cap-90-R12/playlist.m3u8",
        )

    def test_probe_404_means_not_exists(self):
        p = source(lambda r: httpx.Response(404)).probe("x")
        self.assertTrue(p.reachable)
        self.assertFalse(p.exists)

    def test_probe_5xx_means_unreachable(self):
        p = source(lambda r: httpx.Response(503)).probe("x")
        self.assertFalse(p.reachable)

    def test_probe_timeout_means_unreachable(self):
        def handler(request):
            raise httpx.ConnectTimeout("boom")

        p = source(handler).probe("x")
        self.assertFalse(p.reachable)
        self.assertTrue(p.detail)

    def test_probe_resolves_relative_chunklist(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            if request.url.path.endswith("playlist.m3u8"):
                return httpx.Response(200, text=MASTER)
            return httpx.Response(200, text=MEDIA)

        p = source(handler).probe("abc")
        self.assertEqual(
            seen[1], "https://live.example/live/abc/chunklist_w123.m3u8"
        )
        self.assertEqual(p, Probe(True, True, 42, 10.0, p.detail))

    def test_probe_reads_media_playlist_directly(self):
        p = source(lambda r: httpx.Response(200, text=MEDIA)).probe("x")
        self.assertEqual((p.exists, p.media_sequence), (True, 42))

    def test_probe_chunklist_404_means_not_exists(self):
        def handler(request):
            if request.url.path.endswith("playlist.m3u8"):
                return httpx.Response(200, text=MASTER)
            return httpx.Response(404)

        p = source(handler).probe("x")
        self.assertTrue(p.reachable)
        self.assertFalse(p.exists)


    def test_probe_resolves_chunklist_against_redirected_master(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            if request.url.host == "live.example":
                return httpx.Response(
                    302,
                    headers={"Location": "https://edge.example/app/abc/playlist.m3u8"},
                )
            if request.url.path.endswith("playlist.m3u8"):
                return httpx.Response(200, text=MASTER)
            return httpx.Response(200, text=MEDIA)

        p = source(handler).probe("abc")
        self.assertEqual(seen[-1], "https://edge.example/app/abc/chunklist_w123.m3u8")
        self.assertEqual((p.exists, p.media_sequence), (True, 42))

    def test_probe_rejects_redirect_from_https_to_http(self):
        def handler(request):
            if request.url.scheme == "https":
                return httpx.Response(
                    301, headers={"Location": "http://live.example/plain.m3u8"}
                )
            return httpx.Response(200, text=MEDIA)

        p = source(handler).probe("abc")
        self.assertFalse(p.reachable)
        self.assertFalse(p.exists)
        self.assertIn("non-https", p.detail)


class EvaluateTests(unittest.TestCase):
    def prev(self, **kw):
        base = dict(
            state="live",
            live_since=NOW - timedelta(minutes=5),
            media_sequence=42,
            sequence_changed_at=NOW - timedelta(seconds=10),
            detail="",
        )
        base.update(kw)
        return LiveState(**base)

    def probe(self, **kw):
        base = dict(
            reachable=True, exists=True, media_sequence=42, target_duration=6.0
        )
        base.update(kw)
        return Probe(**base)

    def test_evaluate_frozen_encoder_goes_offline(self):
        prev = self.prev(sequence_changed_at=NOW - timedelta(seconds=19))
        self.assertEqual(evaluate(prev, self.probe(), NOW, 3).state, "offline")
        prev = self.prev(sequence_changed_at=NOW - timedelta(seconds=17))
        self.assertEqual(evaluate(prev, self.probe(), NOW, 3).state, "live")

    def test_evaluate_keeps_live_since_while_live(self):
        prev = self.prev()
        out = evaluate(prev, self.probe(media_sequence=43), NOW, 3)
        self.assertEqual(out.state, "live")
        self.assertEqual(out.live_since, prev.live_since)
        self.assertEqual(out.sequence_changed_at, NOW)

    def test_evaluate_sets_live_since_on_transition(self):
        prev = self.prev(state="offline", live_since=None)
        out = evaluate(prev, self.probe(media_sequence=50), NOW, 3)
        self.assertEqual((out.state, out.live_since), ("live", NOW))

    def test_evaluate_first_detection_is_live(self):
        prev = LiveState("unknown", None, None, None, "")
        out = evaluate(prev, self.probe(), NOW, 3)
        self.assertEqual(out.state, "live")
        self.assertEqual(out.live_since, NOW)
        self.assertEqual(out.sequence_changed_at, NOW)

    def test_evaluate_not_exists_is_offline(self):
        out = evaluate(self.prev(), Probe(True, False, None, None, "404"), NOW, 3)
        self.assertEqual(out.state, "offline")
        self.assertIsNone(out.live_since)

    def test_evaluate_unreachable_keeps_previous_fields_but_unknown(self):
        prev = self.prev()
        out = evaluate(prev, Probe(False, False, None, None, "timeout"), NOW, 3)
        self.assertEqual(out.state, "unknown")
        self.assertEqual(out.live_since, prev.live_since)
        self.assertEqual(out.media_sequence, 42)
        self.assertEqual(out.sequence_changed_at, prev.sequence_changed_at)
        self.assertEqual(out.detail, "timeout")

    def test_evaluate_missing_media_sequence_is_offline_with_detail(self):
        # A chunklist that exists but carries no MEDIA-SEQUENCE cannot be
        # judged as advancing, so it is treated as offline (with an explanation).
        out = evaluate(self.prev(), self.probe(media_sequence=None), NOW, 3)
        self.assertEqual(out.state, "offline")
        self.assertIsNone(out.live_since)
        self.assertIn("MEDIA-SEQUENCE", out.detail)

    def test_evaluate_live_unknown_live_keeps_live_since(self):
        prev = self.prev()
        unknown = evaluate(prev, Probe(False, False, None, None, "t"), NOW, 3)
        later = NOW + timedelta(seconds=5)
        for seq in (42, 43):
            out = evaluate(unknown, self.probe(media_sequence=seq), later, 3)
            self.assertEqual(out.state, "live")
            self.assertEqual(out.live_since, prev.live_since)

    def test_evaluate_recovers_after_stale_offline(self):
        prev = self.prev(sequence_changed_at=NOW - timedelta(seconds=60))
        off = evaluate(prev, self.probe(), NOW, 3)
        self.assertEqual(off.state, "offline")
        later = NOW + timedelta(seconds=6)
        out = evaluate(off, self.probe(media_sequence=43), later, 3)
        self.assertEqual((out.state, out.live_since), ("live", later))

    def test_evaluate_stale_stays_offline_without_flapping(self):
        state = self.prev(sequence_changed_at=NOW - timedelta(seconds=60))
        frozen = state.sequence_changed_at
        for i in range(4):
            state = evaluate(state, self.probe(), NOW + timedelta(seconds=6 * i), 3)
            self.assertEqual(state.state, "offline")
            self.assertIsNone(state.live_since)
            self.assertEqual(state.sequence_changed_at, frozen)

    def test_evaluate_boundary_18s_live_19s_offline(self):
        for secs, expected in ((18, "live"), (19, "offline")):
            prev = self.prev(sequence_changed_at=NOW - timedelta(seconds=secs))
            self.assertEqual(evaluate(prev, self.probe(), NOW, 3).state, expected)

    def test_evaluate_uses_default_target_duration(self):
        prev = self.prev(sequence_changed_at=NOW - timedelta(seconds=19))
        out = evaluate(prev, self.probe(target_duration=None), NOW, 3)
        self.assertEqual(out.state, "offline")


if __name__ == "__main__":
    unittest.main()
