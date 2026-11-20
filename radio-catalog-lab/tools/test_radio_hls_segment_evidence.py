"""Offline security tests for opt-in single HLS segment evidence."""
import socket
import unittest
from unittest.mock import patch

from radio_hls_segment_evidence import (
    SEGMENT_BYTES, inspect_segment_bytes, mpeg_ts_packets, plan_one_segment,
    verify_one_segment, safe_segment_transport,
)
from radio_stream_technical_probe import PinnedHttpTransport, ResponseSample

BASE = "https://radio.example.org/hls/live.m3u8"
MIME = "application/vnd.apple.mpegurl"


def manifest(*, a="audio-101.ts", b="audio-102.ts", extra=""):
    return ("#EXTM3U\n#EXT-X-TARGETDURATION:5\n"
            "#EXT-X-MEDIA-SEQUENCE:101\n" + extra +
            "#EXTINF:5,\n" + a + "\n"
            "#EXTINF:5,\n" + b + "\n").encode("utf-8")


def response(body, mime=MIME, status=200, location=""):
    return ResponseSample(status, mime, location, body)


def valid_ts_packets(count=7):
    packets = []
    for i in range(count):
        packets.append(bytes((0x47, 0x40, 0x21, 0x10)) +
                       bytes([i + 1]) * 184)
    return b"".join(packets)


class HlsSegmentEvidenceTests(unittest.TestCase):
    def test_last_segment_selected_from_fully_observed_manifest(self):
        chosen = plan_one_segment(manifest(), MIME, BASE)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.url, "https://radio.example.org/hls/audio-102.ts")

    def test_only_same_origin_no_traversal_or_cross_domain(self):
        for path in (
            "https://evil.example/file.ts",
            "//evil.example/file.ts",
            "/private.ts",
            "../secret.ts",
            "x/../../secret.ts",
            "%2e%2e/secret.ts",
            "%252e%252e/secret.ts",
            "file:///etc/passwd",
            "http://127.0.0.1/stream.ts",
            "ftp://example.com/live.ts",
            "key.bin", "init.m4s", "next.m3u8",
            "x.ts#fragment", "x.ts@evil.example",
            "a\\b.ts", "seg{key}.ts",
        ):
            with self.subTest(path=path):
                self.assertIsNone(plan_one_segment(manifest(b=path), MIME, BASE))

    def test_query_token_allowed_without_url_exposure(self):
        chosen = plan_one_segment(
            manifest(b="segment.ts?sig=abc123&expires=123"), MIME, BASE)
        self.assertTrue(chosen.url.endswith("segment.ts?sig=abc123&expires=123"))

    def test_master_and_encrypted_or_endlisted_media_never_plan_segment(self):
        for data in (
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=64000\nsub/live.m3u8\n",
            manifest(extra='#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'),
            manifest() + b"#EXT-X-ENDLIST\n",
            manifest(extra='#EXT-X-MAP:URI="init.mp4"\n'),
        ):
            with self.subTest(data=data[:50]):
                self.assertIsNone(plan_one_segment(data, MIME, BASE))

    def test_oversized_or_incomplete_manifest_never_plan_segment(self):
        self.assertIsNone(plan_one_segment(manifest()[:-1], MIME, BASE))
        self.assertIsNone(plan_one_segment(manifest(extra="#"+"x"*4200+"\n"), MIME, BASE))

    def test_four_ts_packets_and_non_null_pids_are_structural_only(self):
        result = mpeg_ts_packets(valid_ts_packets(5))
        self.assertEqual(result["state"], "mpeg_ts_structure")
        self.assertEqual(result["packetCount"], 5)
        self.assertFalse(result["publicationAllowed"])
        observed = inspect_segment_bytes(valid_ts_packets(5))
        self.assertEqual(observed["state"], "mpeg_ts_structure_only")
        self.assertEqual(observed["codecHint"], "mpegts_unverified_audio")

    def test_video_only_ts_cannot_be_called_decoded_audio(self):
        out = inspect_segment_bytes(valid_ts_packets(6))
        self.assertNotIn("decoded_pcm", str(out))
        self.assertFalse(out["publicationAllowed"])

    def test_corrupt_ts_or_null_pid_is_not_evidence(self):
        bad = bytearray(valid_ts_packets(5))
        bad[188] = 0
        null = bytes((0x47, 0x1F, 0xFF, 0x10)) + bytes(184)
        for candidate in (bytes(bad), null * 5, valid_ts_packets(3)):
            self.assertEqual(mpeg_ts_packets(candidate)["state"], "not_confirmed")

    def test_ts_segment_byte_budget_enforced(self):
        self.assertEqual(inspect_segment_bytes(bytes(SEGMENT_BYTES + 1))["state"],
                         "not_confirmed")

    def test_audio_adts_frame_chain_is_distinct_from_ts_structure(self):
        # Three valid ADTS headers separated by 100-byte frames.
        hdr = bytes((0xFF, 0xF1, 0x50, 0x80, 0x0C, 0x9F, 0xFC))
        packet = hdr + bytes(93)
        out = inspect_segment_bytes(packet * 3)
        self.assertEqual(out["state"], "audio_frame_chain")
        self.assertEqual(out["codecHint"], "aac_adts")

    def test_finite_segment_one_get_and_no_authorization(self):
        seen = []
        def manifest_request(u):
            seen.append(("manifest", u))
            return response(manifest())
        def segment_request(u):
            seen.append(("segment", u))
            return response(valid_ts_packets(6), "video/mp2t")
        out = verify_one_segment(BASE, manifest_request, segment_request)
        self.assertEqual(out["state"], "segment_structural_evidence")
        self.assertEqual(out["manifestKind"], "live_manifest_candidate")
        self.assertEqual(out["segmentEvidence"]["state"], "mpeg_ts_structure_only")
        self.assertFalse(out["technicalQualified"])
        self.assertFalse(out["publicationAllowed"])
        self.assertNotIn("radio.example", str(out))
        self.assertNotIn("audio-102", str(out))
        self.assertEqual(len(seen), 2)

    def test_manifest_vod_does_not_trigger_segment_request(self):
        called = []
        out = verify_one_segment(
            BASE,
            lambda _: response(manifest() + b"#EXT-X-ENDLIST\n"),
            lambda u: called.append(u))
        self.assertEqual(out["state"], "no_safe_simple_segment")
        self.assertEqual(called, [])

    def test_redirect_to_external_host_never_followed(self):
        seen = []
        def segment_request(u):
            seen.append(u)
            return response(b"", "text/html", 302, "http://127.0.0.1/private")
        out = verify_one_segment(BASE, lambda _: response(manifest()), segment_request)
        self.assertEqual(out["state"], "segment_http_unconfirmed")
        self.assertEqual(len(seen), 1)

    def test_non_audio_mime_html_rejected(self):
        out = verify_one_segment(BASE, lambda _: response(manifest()),
                                 lambda _: response(b"<html>oops</html>", "text/html"))
        self.assertEqual(out["state"], "segment_non_audio_mime")

    def test_private_manifest_is_rejected_before_any_network(self):
        calls = []
        out = verify_one_segment(
            "http://127.0.0.1/live.m3u8", lambda u: calls.append(u),
            lambda u: calls.append(u))
        self.assertEqual(out["state"], "unsafe_or_failed_segment_request")
        self.assertEqual(calls, [])

    def test_pinned_transport_segment_range_and_16k_budget(self):
        self.assertIsInstance(safe_segment_transport(), PinnedHttpTransport)
        self.assertTrue(safe_segment_transport().segment_mode)
        connections = []
        payload = valid_ts_packets(100)
        class FakeResponse:
            status = 206
            def __init__(self):
                self.pos = 0
            def getheader(self, name, default=""):
                return "video/mp2t" if name == "Content-Type" else default
            def read1(self, n):
                if self.pos >= len(payload):
                    return b""
                p = min(len(payload), self.pos + 2048, self.pos + n)
                out = payload[self.pos:p]
                self.pos = p
                return out
        class FakeConnection:
            def __init__(self, host, port, timeout=None, context=None):
                self.host, self.port = host, port
                connections.append(self)
            def request(self, method, target, headers):
                self.headers = headers
                self._create_connection((self.host, self.port))
            def getresponse(self):
                return FakeResponse()
            def close(self):
                pass
        resolver = lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]
        with patch("radio_stream_technical_probe.http.client.HTTPSConnection",
                   FakeConnection), patch(
                     "radio_stream_technical_probe.socket.create_connection",
                     return_value=object()) as sock:
            transport = PinnedHttpTransport(resolver=resolver, segment_mode=True)
            result = transport.request("https://radio.example.org/hls/audio.ts")
        self.assertEqual(len(result.body), 16384)
        self.assertEqual(connections[0].headers["Range"], "bytes=0-16383")
        self.assertEqual(sock.call_args.args[0], ("8.8.8.8", 443))


if __name__ == "__main__":
    unittest.main()
