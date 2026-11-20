"""No-network regression tests for bounded, pinned radio stream evidence."""
import datetime as dt
import json
import socket
import unittest
from unittest.mock import patch

from radio_stream_technical_probe import (
    MAX_BYTES, MAX_REDIRECTS, PinnedHttpTransport, ResponseSample,
    UnsafeEndpoint, classify_sample, probe_candidates, probe_url,
    public_resolved_ips, validate_endpoint,
)

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def sample(status=200, mime="audio/mpeg", data=b"ID3\x04\x00\x00" + b"\x00"*60,
           location=""):
    return ResponseSample(status, mime, location, data)


def station(uid=A, url="https://radio.example.org/stream",
            status="candidate_requires_qualification"):
    return {"stationuuid": uid, "streamUrl": url, "status": status}


def report(stations):
    return {"schemaVersion": 1, "publicationAllowed": False, "candidates": stations}


class TechnicalStreamProbeTests(unittest.TestCase):
    def test_endpoint_validation_accepts_https_and_http_standard_ports(self):
        self.assertEqual(validate_endpoint("https://radio.example.org/live?a=1").hostname,
                         "radio.example.org")
        self.assertEqual(validate_endpoint("http://radio.example.org:8000/live").port, 8000)

    def test_endpoint_blocks_loopback_private_link_local_and_metadata(self):
        for bad in ("http://127.0.0.1/a", "https://localhost",
                    "http://192.168.1.1/a", "http://10.1.2.3/a",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://172.16.0.4/a", "http://[::1]/a",
                    "http://[fe80::1]/a", "https://example.local/x"):
            with self.subTest(bad=bad), self.assertRaises(UnsafeEndpoint):
                validate_endpoint(bad)

    def test_endpoint_blocks_credentials_non_http_and_fragments(self):
        for bad in ("file:///etc/passwd", "ftp://radio.example.org/stream",
                    "https://user:secret@radio.example.org/x",
                    "https://radio.example.org/x#anchor", "https://one",
                    "https://radio.example.org./foo", "https://bad%40host.test/",
                    "https://radio.example.org/\r\nEvil: 1"):
            with self.subTest(bad=bad), self.assertRaises(UnsafeEndpoint):
                validate_endpoint(bad)

    def test_dns_rejects_mixed_public_private_results_even_if_first_public(self):
        def resolver(host, port, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            ]
        with self.assertRaisesRegex(UnsafeEndpoint, "private_dns_answer"):
            public_resolved_ips("radio.example.org", 443, resolver)

    def test_dns_dedupes_checked_public_ips(self):
        def resolver(host, port, **kwargs):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
            ]
        self.assertEqual(public_resolved_ips("radio.example.org", 443, resolver),
                         ["8.8.8.8", "1.1.1.1"])

    def test_dns_empty_malformed_private_and_resolution_failure(self):
        bad = [
            (lambda h, p, **k: [], "dns_empty"),
            (lambda h, p, **k: [(0,0,0,"",("::1",p))], "private_dns_answer"),
            (lambda h, p, **k: [(0,0,0,"",("not-an-ip",p))], "malformed_dns"),
        ]
        for resolver, expected in bad:
            with self.subTest(expected=expected), self.assertRaisesRegex(UnsafeEndpoint,expected):
                public_resolved_ips("radio.example.org", 443, resolver)
        def offline(h, p, **kwargs):
            raise OSError("offline")
        with self.assertRaisesRegex(UnsafeEndpoint, "dns_failed"):
            public_resolved_ips("radio.example.org", 443, offline)

    def test_positive_media_magic_signatures(self):
        formats = {
            b"ID3\x04\x00\x00" + b"\x00"*32: "mp3_id3",
            b"\xff\xfb\x90\x64" + b"\x00"*30: "mpeg_or_aac_frame",
            b"\xff\xf1\x50\x80" + b"\x00"*30: "mpeg_or_aac_frame",
            b"OggS\x00\x02" + b"\x00"*32: "ogg",
            b"fLaC" + b"\x00"*32: "flac",
            b"RIFF\x00\x00\x00\x00WAVEfmt ": "wav",
            b"\x1a\x45\xdf\xa3" + b"\x00"*32: "webm",
            b"\x00\x00\x00\x18ftypisom": "mp4_container",
        }
        for payload, expected in formats.items():
            with self.subTest(expected=expected):
                self.assertEqual(classify_sample(payload, "application/octet-stream"),
                                 ("audio_sample_ok", expected))

    def test_playlist_urls_are_not_blindly_followed_or_approved(self):
        for data, mime in (
            (b"#EXTM3U\nhttp://127.0.0.1/internal", "audio/mpeg"),
            (b"[playlist]\nFile1=http://127.0.0.1/", "audio/x-scpls"),
            (b"#EXTM3U\n#EXT-X-VERSION:3", "application/vnd.apple.mpegurl"),
        ):
            with self.subTest(mime=mime):
                self.assertEqual(classify_sample(data, mime),
                                 ("playlist_pending", "playlist"))

    def test_mime_type_alone_is_not_audio_verification(self):
        self.assertEqual(classify_sample(b"not valid audio", "audio/mpeg"),
                         ("audio_mime_only", "unrecognized_audio_payload"))
        self.assertEqual(classify_sample(b"<html>Oops</html>", "text/html"),
                         ("not_confirmed_audio", "unknown"))

    def test_good_audio_is_only_a_sample_not_release_approval(self):
        calls = []
        def request(url):
            calls.append(url)
            return sample()
        result = probe_url("https://radio.example.org/stream", request)
        self.assertEqual(result["verdict"], "audio_sample_ok")
        self.assertEqual(result["redirectCount"], 0)
        self.assertEqual(result["sampleBytes"], 66)
        self.assertNotIn("radio.example.org", json.dumps(result))
        self.assertEqual(len(calls), 1)

    def test_hls_manifest_requires_followup_technical_implementation(self):
        result = probe_url("https://radio.example.org/live.m3u8",
                           lambda _: sample(mime="application/vnd.apple.mpegurl",
                                            data=b"#EXTM3U\n#EXTINF:3,\nsegment.ts"))
        self.assertEqual(result["verdict"], "playlist_pending")

    def test_safely_follows_https_redirect_with_explicit_new_request(self):
        requested = []
        def request(url):
            requested.append(url)
            if url.endswith("/start"):
                return sample(status=302, location="/stream")
            return sample()
        result = probe_url("https://radio.example.org/start", request)
        self.assertEqual(result["verdict"], "audio_sample_ok")
        self.assertEqual(result["redirectCount"], 1)
        self.assertEqual(requested, ["https://radio.example.org/start",
                                      "https://radio.example.org/stream"])

    def test_redirect_to_local_ip_is_blocked_before_request(self):
        requested = []
        def request(url):
            requested.append(url)
            return sample(status=302, location="http://127.0.0.1/private")
        result = probe_url("https://radio.example.org/live", request)
        self.assertEqual(result["verdict"], "blocked_unsafe")
        self.assertEqual(len(requested), 1)

    def test_http_downgrade_is_held_for_review(self):
        result = probe_url("https://radio.example.org/live",
                           lambda _: sample(status=302,
                                            location="http://radio.example.org/stream"))
        self.assertEqual(result["verdict"], "needs_review")
        self.assertEqual(result["reason"], "tls_downgrade")

    def test_redirect_cycles_and_excess_redirects_are_bounded(self):
        result = probe_url("https://radio.example.org/a",
                           lambda url: sample(status=302,
                                              location="/b" if url.endswith("/a") else "/a"))
        self.assertEqual(result["reason"], "redirect_cycle")
        counter = [0]
        def endless(url):
            counter[0] += 1
            return sample(status=302, location=f"/next-{counter[0]}")
        result = probe_url("https://radio.example.org/a", endless)
        self.assertEqual(result["reason"], "redirect_limit_or_missing_location")
        self.assertEqual(counter[0], MAX_REDIRECTS+1)

    def test_http_errors_and_network_errors_do_not_count_as_audio(self):
        self.assertEqual(probe_url("https://radio.example.org/live",
                                   lambda _: sample(status=404))["verdict"], "needs_review")
        def offline(url):
            raise OSError("network unreachable")
        self.assertEqual(probe_url("https://radio.example.org/live", offline)["verdict"],
                         "needs_review")

    def test_probe_candidate_report_never_authorizes_publication(self):
        obs = probe_candidates(report([station()]), lambda _: sample(),
                               observation_day=dt.date(2026, 11, 20))
        self.assertFalse(obs["publicationAllowed"])
        self.assertEqual(obs["checkedCount"], 1)
        self.assertEqual(obs["audioEvidenceCount"], 1)
        self.assertEqual(obs["technicalVerifiedCount"], 0)
        self.assertFalse(obs["checks"][0]["publicationAllowed"])

    def test_duplicate_identity_status_skipped_not_auto_merged(self):
        obs = probe_candidates(report([
            station(A, status="needs_duplicate_review"),
            station(B, status="candidate_requires_qualification"),
        ]), lambda _: sample())
        self.assertEqual(obs["checkedCount"], 1)
        self.assertEqual(obs["checks"][0]["stationuuid"], B)

    def test_missing_or_non_http_stream_skipped_or_blocked(self):
        obs = probe_candidates(report([
            station(A, url=""),
            station(B, url="http://127.0.0.1/private"),
        ]), lambda _: sample())
        self.assertEqual(obs["checkedCount"], 1)
        self.assertEqual(obs["checks"][0]["verdict"], "blocked_unsafe")

    def test_probe_budget_is_bounded_even_for_larger_reports(self):
        calls = []
        def request(url):
            calls.append(url)
            return sample()
        obs = probe_candidates(report([station(A), station(B), station(C)]),
                               request, limit=2)
        self.assertEqual(obs["checkedCount"], 2)
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ValueError):
            probe_candidates(report([station(A)]), request, limit=100)

    def test_invalid_discovery_report_or_repeated_uuid_refused(self):
        with self.assertRaises(ValueError):
            probe_candidates({"schemaVersion": 1, "publicationAllowed": True,
                              "candidates": [station()]}, lambda _: sample())
        with self.assertRaises(ValueError):
            probe_candidates(report([station(A), station(A)]), lambda _: sample(),
                             limit=5)

    def test_untrusted_http_response_bytes_never_exceed_sample_bound(self):
        oversized = b"ID3" + b"m" * 10000
        out = probe_url("https://radio.example.org/s", lambda _: sample(data=oversized))
        self.assertEqual(out["sampleBytes"], MAX_BYTES)

    def test_dns_pinning_does_not_trust_proxy_environment(self):
        # Smoke-check the transport surface: no urllib opener or proxy API.
        transport = PinnedHttpTransport(resolver=lambda *a, **k: [])
        with self.assertRaises(UnsafeEndpoint):
            transport.request("http://radio.example.org/live")

    def test_result_never_contains_user_supplied_url_or_secret(self):
        raw = "https://radio.example.org/live?token=some-public-source-secret"
        out = probe_url(raw, lambda _: sample())
        self.assertNotIn("token=", json.dumps(out))
        self.assertEqual(len(out["streamSha256"]), 64)


if __name__ == "__main__":
    unittest.main()
