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
            "http://evil.example/file.ts",
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


    def test_absolute_https_cdn_segment_is_checked_with_one_request(self):
        target = "https://audio-cdn.example.org/hls/seg-105.ts?token=ABCD%20EFGH"
        chosen = plan_one_segment(manifest(b=target), MIME, BASE)
        self.assertEqual(chosen.url, target)
        requested = []
        def segment_request(url):
            requested.append(url)
            return response(valid_ts_packets(5), "video/mp2t", status=206)
        outcome = verify_one_segment(
            BASE, lambda _: response(manifest(b=target)), segment_request)
        self.assertEqual(outcome["state"], "segment_structural_evidence")
        self.assertEqual(requested, [target])
        self.assertNotIn("audio-cdn", str(outcome))
        self.assertNotIn("ABCD", str(outcome))
        self.assertFalse(outcome["publicationAllowed"])

    def test_external_http_or_private_cdn_segment_is_never_fetched(self):
        for target in ("http://audio-cdn.example.org/hls/audio.ts",
                       "https://127.0.0.1/audio.ts",
                       "https://user:password@cdn.example.org/live.ts",
                       "https://[::1]/audio.ts"):
            with self.subTest(target=target):
                self.assertIsNone(plan_one_segment(manifest(b=target), MIME, BASE))
                called = []
                outcome = verify_one_segment(
                    BASE, lambda _: response(manifest(b=target)),
                    lambda u: called.append(u))
                self.assertEqual(called, [])
                self.assertFalse(outcome["publicationAllowed"])

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



    def test_only_one_variant_can_be_followed(self):
        from radio_hls_segment_evidence import plan_single_variant
        master = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                  b"child/live.m3u8\n")
        plan = plan_single_variant(master, MIME, BASE)
        self.assertEqual(plan.url, "https://radio.example.org/hls/child/live.m3u8")

    def test_single_variant_to_segment_follows_only_three_safe_gets(self):
        master = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                  b"child/live.m3u8\n")
        fetched = []
        def read_manifest(u):
            fetched.append(("manifest", u))
            return response(master if u == BASE else manifest())
        def read_segment(u):
            fetched.append(("segment", u))
            return response(valid_ts_packets(5), "video/mp2t")
        result = verify_one_segment(BASE, read_manifest, read_segment)
        self.assertEqual(result["manifestKind"], "master_single_variant_pending")
        self.assertEqual(result["childManifestKind"], "live_manifest_candidate")
        self.assertEqual(result["state"], "segment_structural_evidence")
        self.assertEqual([tag for tag, _ in fetched], ["manifest", "manifest", "segment"])
        self.assertNotIn("child/live.m3u8", str(result))
        self.assertFalse(result["technicalQualified"])

    def test_master_with_two_variants_never_selects_arbitrarily(self):
        data = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                b"low/live.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=192000\n"
                b"high/live.m3u8\n")
        requests = []
        result = verify_one_segment(BASE, lambda u: response(data),
                                    lambda u: requests.append(u))
        self.assertEqual(result["state"], "no_safe_simple_segment")
        self.assertEqual(requests, [])

    def test_master_external_variant_and_traversal_never_requested(self):
        from radio_hls_segment_evidence import plan_single_variant
        for reference in ("http://other.example.org/live.m3u8",
                          "//other.example.org/live.m3u8",
                          "../private.m3u8", "%2e%2e/private.m3u8",
                          "file:///etc/secrets.m3u8",
                          "child.m3u8#part", "child{token}.m3u8"):
            master = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                      + reference + "\n").encode()
            with self.subTest(reference=reference):
                self.assertIsNone(plan_single_variant(master, MIME, BASE))
                requested = []
                output = verify_one_segment(BASE,
                    lambda u: requested.append(u) or response(master),
                    lambda u: requested.append(u))
                self.assertEqual(len(requested), 1)
                self.assertEqual(output["state"], "no_safe_single_variant")


    def test_single_https_cdn_variant_is_allowed_without_auto_certification(self):
        from radio_hls_segment_evidence import plan_single_variant
        uri = "https://cdn.example.org/media/quality.m3u8?token=abc%20def"
        master = ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                  + uri + "\n").encode("utf-8")
        plan = plan_single_variant(master, MIME, BASE)
        self.assertEqual(plan.url, uri)
        requested = []
        def fetch(u):
            requested.append(("manifest", u))
            return response(master if u == BASE else manifest())
        def seg(u):
            requested.append(("segment", u))
            return response(valid_ts_packets(6), "video/mp2t")
        result = verify_one_segment(BASE, fetch, seg)
        self.assertEqual(result["state"], "segment_structural_evidence")
        self.assertEqual(result["childManifestKind"], "live_manifest_candidate")
        self.assertEqual(requested[1][1], uri)
        self.assertTrue(requested[2][1].startswith("https://cdn.example.org/media/"))
        self.assertEqual(result["publicationAllowed"], False)
        self.assertNotIn("cdn.example.org", str(result))

    def test_no_nested_master_playlist(self):
        master = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                  b"child/live.m3u8\n")
        reads = []
        def fetch(u):
            reads.append(u)
            return response(master)
        result = verify_one_segment(BASE, fetch, lambda u: reads.append(u))
        self.assertEqual(result["childManifestKind"], "master_single_variant_pending")
        self.assertEqual(result["state"], "child_not_simple_live_media")
        self.assertEqual(len(reads), 2)

    def test_child_redirect_never_follows_to_unsafe_network(self):
        master = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=96000\n"
                  b"child/live.m3u8\n")
        reads = []
        def fetch(u):
            reads.append(u)
            if u == BASE:
                return response(master)
            return response(b"", status=302, location="http://127.0.0.1/")
        result = verify_one_segment(BASE, fetch, lambda u: reads.append(u))
        # Rejecting an unsafe redirect is stronger than merely marking 302 pending.
        self.assertEqual(result["state"], "unsafe_or_failed_segment_request")
        self.assertEqual(len(reads), 2)
        self.assertNotIn("127.0.0.1", str(result))


    def test_root_https_redirect_to_public_cdn_with_pinned_fetch(self):
        fetched = []
        final = "https://cdn.example.org/hls/stream.m3u8"
        def fetch(url):
            fetched.append(url)
            if url == BASE:
                return response(b"", status=302, location=final)
            return response(manifest())
        def segment(url):
            fetched.append(url)
            return response(valid_ts_packets(5), "video/mp2t")
        result = verify_one_segment(BASE, fetch, segment)
        self.assertEqual(result["state"], "segment_structural_evidence")
        self.assertEqual(fetched, [
            BASE, final, "https://cdn.example.org/hls/audio-102.ts"])
        self.assertNotIn("cdn.example", str(result))
        self.assertFalse(result["publicationAllowed"])

    def test_no_https_to_http_redirect_and_no_unsafe_private_target(self):
        for dest in ("http://cdn.example.org/stream.m3u8",
                     "https://127.0.0.1/secret.m3u8",
                     "http://169.254.169.254/latest.m3u8"):
            seen = []
            def fetch(url):
                seen.append(url)
                return response(b"", status=302, location=dest)
            output = verify_one_segment(BASE, fetch, lambda url: seen.append(url))
            self.assertIn(output["state"],
                          {"manifest_fetch_incomplete",
                           "unsafe_or_failed_segment_request"})
            self.assertEqual(seen, [BASE])
            self.assertFalse(output["publicationAllowed"])

    def test_manifest_redirect_cycle_and_three_hops_fail_closed(self):
        seen = []
        def cycle(url):
            seen.append(url)
            return response(b"", status=301,
                            location=("https://radio.example.org/loop.m3u8"
                                      if url == BASE else BASE))
        output = verify_one_segment(BASE, cycle, lambda url: seen.append(url))
        self.assertEqual(output["state"], "manifest_fetch_incomplete")
        self.assertEqual(len(seen), 2)
        self.assertFalse(output["publicationAllowed"])

        n = 0
        def chain(url):
            nonlocal n
            n += 1
            return response(b"", status=302,
                            location=f"https://radio.example.org/redir{n}.m3u8")
        output = verify_one_segment(BASE, chain, lambda url: None)
        self.assertEqual(output["state"], "manifest_fetch_incomplete")
        self.assertEqual(n, 3)


    def test_sanitized_reasons_distinguish_fmp4_and_external_media(self):
        from radio_hls_segment_evidence import pending_media_reference_reason
        examples = (
            ("chunks/first.m4s", "fragmented_mp4_requires_init"),
            ("https://cdn.example.org/secret123.ts", "absolute_segment_reference_pending"),
            ("/media/private.ts", "root_relative_segment_pending"),
            ("playlist.mpd", "unsupported_segment_extension"),
            ("../secret.ts", "path_traversal"),
        )
        for reference, expected in examples:
            with self.subTest(reference=reference):
                reason = pending_media_reference_reason(
                    manifest(b=reference), MIME, BASE)
                self.assertEqual(reason, expected)
                self.assertNotIn(reference, reason)
                self.assertNotIn("secret", reason)

    def test_pending_reason_never_discloses_signed_segment_query(self):
        data = manifest(b="cdn-123.m4s?sig=SENSITIVE_TOKEN_123")
        out = verify_one_segment(BASE, lambda _: response(data), lambda _: None)
        self.assertEqual(out["state"], "no_safe_simple_segment")
        self.assertEqual(out["planningReason"], "fragmented_mp4_requires_init")
        self.assertNotIn("SENSITIVE_TOKEN", str(out))
        self.assertFalse(out["technicalQualified"])
        self.assertFalse(out["publicationAllowed"])

if __name__ == "__main__":
    unittest.main()
