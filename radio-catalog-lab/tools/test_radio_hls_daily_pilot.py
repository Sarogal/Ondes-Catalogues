"""Offline contract tests for non-publishing HLS radio selection and probing."""
import datetime as dt
import unittest

from radio_hls_daily_pilot import hls_preview, select_hls_candidates
from radio_stream_technical_probe import ResponseSample

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def row(uid=A, url="https://radio.example.org/metal.m3u8",
        status="candidate_requires_qualification"):
    return {"stationuuid": uid, "streamUrl": url, "status": status}


def report(rows):
    return {"schemaVersion": 1, "publicationAllowed": False, "candidates": rows}


def sample():
    return ResponseSample(200, "application/vnd.apple.mpegurl", "",
                          b"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:12\n"
                          b"#EXTINF:5,\na.ts\n#EXTINF:5,\nb.ts\n")


class HlsDailyPilotTests(unittest.TestCase):
    def test_new_uuid_is_eligible_without_fixed_whitelist(self):
        result = select_hls_candidates(report([row()]), day=dt.date(2026, 11, 20))
        self.assertEqual(result, [(A, "https://radio.example.org/metal.m3u8")])

    def test_non_hls_urls_and_duplicate_review_not_probed(self):
        values = [row(A, "https://radio.example.org/live.mp3"),
                  row(B, "https://radio.example.org/listen.m3u8",
                      status="needs_duplicate_review"),
                  row(C, "https://radio.example.org/live.m3u8")]
        selected = select_hls_candidates(report(values), day=dt.date(2026, 11, 20))
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][0], C)

    def test_querystring_m3u8_is_recognized(self):
        values = [row(A, "https://radio.example.org/live.m3u8?token=example")]
        selected = select_hls_candidates(report(values), day=dt.date(2026, 11, 20))
        self.assertEqual(len(selected), 1)

    def test_safe_hls_metadata_never_claims_audio_or_publication(self):
        calls = []
        def request(url):
            calls.append(url)
            return sample()
        result = hls_preview(report([row()]), request, day=dt.date(2026, 11, 20))
        self.assertEqual(result["checkedCount"], 1)
        self.assertEqual(result["liveManifestCandidateCount"], 1)
        self.assertEqual(result["technicalVerifiedCount"], 0)
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["checks"][0]["verdict"], "playlist_pending")
        self.assertEqual(result["checks"][0]["hlsKind"], "live_manifest_candidate")
        self.assertNotIn("a.ts", str(result))
        self.assertNotIn("radio.example.org", str(result))
        self.assertEqual(calls, ["https://radio.example.org/metal.m3u8"])

    def test_vod_and_hls_failure_are_not_live(self):
        sample_vod = ResponseSample(
            200, "application/vnd.apple.mpegurl", "",
            b"#EXTM3U\n#EXT-X-TARGETDURATION:5\n#EXTINF:5,\na.ts\n"
            b"#EXTINF:5,\nb.ts\n#EXT-X-ENDLIST\n")
        values = report([row(A), row(B, "https://radio.example.org/live2.m3u8")])
        result = hls_preview(values, lambda _: sample_vod, day=dt.date(2026, 11, 20))
        self.assertEqual(result["liveManifestCandidateCount"], 0)
        self.assertEqual(result["manifestKinds"]["media_finite_playlist"], 2)

    def test_all_bad_reports_fail_closed(self):
        for payload in (
            {"schemaVersion": 1, "publicationAllowed": True, "candidates": [row()]},
            report([row(A), row(A)]),
            report([row(A, status="approved")]),
            report([row("not-uuid")]),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                select_hls_candidates(payload, day=dt.date(2026, 11, 20))

    def test_candidate_budget_is_bounded_and_rotated(self):
        rows = [row(str(i).zfill(8) + "-0000-4000-8000-000000000000",
                    "https://radio.example.org/live.m3u8")
                for i in range(1, 14)]
        data = report(rows)
        day = dt.date(2026, 11, 20)
        first = select_hls_candidates(data, day=day, limit=5)
        second = select_hls_candidates(data, day=day + dt.timedelta(days=1), limit=5)
        self.assertEqual(len(first), 5)
        self.assertEqual(len(second), 5)
        self.assertNotEqual({r[0] for r in first}, {r[0] for r in second})
        with self.assertRaises(ValueError):
            select_hls_candidates(data, day=day, limit=6)

    def test_no_hls_urls_requires_no_network(self):
        calls = []
        result = hls_preview(report([row(url="https://radio.example.org/live.mp3")]),
                             lambda u: calls.append(u),
                             day=dt.date(2026, 11, 20))
        self.assertEqual(result["checkedCount"], 0)
        self.assertEqual(calls, [])



    def test_optin_is_impossible_without_explicit_segment_sampler(self):
        with self.assertRaises(ValueError):
            hls_preview(report([row()]), lambda _: sample(),
                        day=dt.date(2026, 11, 20), check_one_segment=True)

    def test_one_total_segment_on_two_live_manifests(self):
        seen = []
        ts = (bytes((0x47, 0x40, 0x21, 0x10)) + bytes(184)) * 6
        def manifest_request(url):
            seen.append(("manifest", url))
            return sample()
        def segment_request(url):
            seen.append(("segment", url))
            return ResponseSample(206, "video/mp2t", "", ts)
        values = report([row(A), row(B, "https://radio.example.org/hls2.m3u8")])
        output = hls_preview(values, manifest_request,
                             day=dt.date(2026, 11, 20),
                             check_one_segment=True,
                             segment_request=segment_request)
        self.assertEqual(output["checkedCount"], 2)
        self.assertEqual(output["segmentVerificationAttemptCount"], 1)
        self.assertEqual(output["segmentStructuralEvidenceCount"], 1)
        self.assertEqual(sum(k == "segment" for k, _ in seen), 1)
        self.assertEqual(output["technicalVerifiedCount"], 0)
        self.assertFalse(output["publicationAllowed"])
        self.assertNotIn("audio-102", str(output))
        self.assertNotIn("hls2.m3u8", str(output))
        self.assertEqual(sum("segmentCheck" in row for row in output["checks"]), 1)

    def test_vod_without_live_candidates_never_requests_segment(self):
        complete = ResponseSample(
            200, "application/vnd.apple.mpegurl", "",
            sample().body + b"#EXT-X-ENDLIST\n")
        calls = []
        output = hls_preview(
            report([row()]), lambda _: complete,
            day=dt.date(2026, 11, 20), check_one_segment=True,
            segment_request=lambda url: calls.append(url))
        self.assertEqual(output["segmentVerificationAttemptCount"], 0)
        self.assertEqual(output["segmentStructuralEvidenceCount"], 0)
        self.assertEqual(calls, [])

    def test_segment_redirect_is_not_interpreted_as_evidence(self):
        output = hls_preview(
            report([row()]), lambda _: sample(),
            day=dt.date(2026, 11, 20), check_one_segment=True,
            segment_request=lambda _: ResponseSample(
                302, "", "http://127.0.0.1/", b""))
        self.assertEqual(output["segmentVerificationAttemptCount"], 1)
        self.assertEqual(output["segmentStructuralEvidenceCount"], 0)
        self.assertEqual(output["checks"][0]["segmentCheck"]["state"],
                         "segment_http_unconfirmed")
        self.assertNotIn("127.0.0.1", str(output))

if __name__ == "__main__":
    unittest.main()
