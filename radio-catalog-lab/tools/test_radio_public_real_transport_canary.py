"""Strict no-socket coverage for public directory radio live transport pilot."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from radio_public_real_transport_canary import qualify_public_candidates
from radio_stream_technical_probe import ResponseSample


def raws(n=7, *, suffix=".mp3", codec="MP3"):
    return [
        {"stationuuid": str(uuid.UUID(int=i + 1)),
         "name": f"Heavy Metal Radio {i}", "tags": "metal,rock",
         "countrycode": "FR", "lastcheckok": 1, "codec": codec,
         "url_resolved": f"https://public-radio.example.org/stream-{i}{suffix}"}
        for i in range(n)
    ]


def fake_audio(url):
    return ResponseSample(status=200, content_type="audio/mpeg",
                          location="", body=b"ID3" + b"\x00" * 35)


class PublicLiveTransportCanaryTests(unittest.TestCase):
    def test_five_real_probe_functions_to_private_independent_ledger(self):
        touched = []
        def request(url):
            touched.append(url)
            return fake_audio(url)
        with tempfile.TemporaryDirectory() as root:
            summary, ledger = qualify_public_candidates(
                raws(), day="2026-11-20", request=request,
                scratch_parent=Path(root))
            self.assertEqual(summary["actualNetworkProbes"], 5)
            self.assertEqual(summary["audioSampleEvidenceCount"], 5)
            self.assertEqual(summary["eligibleDirectCandidatesOnPage"], 7)
            self.assertEqual(summary["historicalPrivateStationsChecked"], 0)
            self.assertEqual(len(touched), 5)
            self.assertEqual(len(set(touched)), 5)
            self.assertEqual(ledger["streamHistoryMode"], "per_stream")
            self.assertEqual(len(ledger["records"]), 5)
            self.assertFalse(ledger["publicationAllowed"])
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertNotIn("https://", json.dumps(summary) + json.dumps(ledger))

    def test_broken_stream_never_autodeletes(self):
        def fails(url):
            return ResponseSample(status=404, content_type="", location="", body=b"")
        with tempfile.TemporaryDirectory() as root:
            summary, ledger = qualify_public_candidates(
                raws(), day="2026-11-20", request=fails,
                scratch_parent=Path(root))
            self.assertEqual(summary["verdictCounts"], {"needs_review": 5})
            self.assertEqual(summary["oldStationsDeleted"], 0)
            self.assertEqual(summary["technicallyQualifiedCount"], 0)
            self.assertEqual(len(ledger["records"]), 5)

    def test_hls_is_not_mislabeled_as_direct_aac(self):
        data = raws(4)
        data.extend(raws(2, suffix=".m3u8", codec="AAC"))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "Insufficient"):
                qualify_public_candidates(data, day="2026-11-20",
                                          request=fake_audio,
                                          scratch_parent=Path(root))

    def test_requires_at_least_five_eligible_distinct_uuids(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "Insufficient"):
                qualify_public_candidates(raws(4), day="2026-11-20",
                                          request=fake_audio,
                                          scratch_parent=Path(root))

    def test_public_directory_input_ceiling(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "response size"):
                qualify_public_candidates(raws(101), day="2026-11-20",
                                          request=fake_audio,
                                          scratch_parent=Path(root))

    def test_candidate_uuids_not_allowlisted(self):
        sample = raws(5)
        sample[0]["stationuuid"] = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as root:
            summary, ledger = qualify_public_candidates(
                sample, day="2026-11-20", request=fake_audio,
                scratch_parent=Path(root))
            self.assertEqual(len(ledger["records"]), 5)
            self.assertEqual(summary["editorialApprovals"], 0)


if __name__ == "__main__":
    unittest.main()
