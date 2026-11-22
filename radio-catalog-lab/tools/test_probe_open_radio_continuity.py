#!/usr/bin/env python3
"""Offline tests for live-continuity evidence without stream qualification."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_open_radio_continuity import summarize


class ContinuityEvidenceTests(unittest.TestCase):
    def test_three_distinct_audio_windows_are_evidence_only(self):
        a = [
            {"transport_audio_prefix": True, "prefix_sha256": c * 64}
            for c in "abc"
        ]
        x = summarize(a)
        self.assertTrue(x["time_separated_audio_evidence"])
        self.assertFalse(x["publication_allowed"])
        self.assertFalse(x["playback_decoding_confirmed"])
        self.assertTrue(x["editorial_review_required"])

    def test_repeated_audio_rejected_as_no_diversity(self):
        a = [
            {"transport_audio_prefix": True, "prefix_sha256": "a" * 64}
            for _ in range(3)
        ]
        self.assertFalse(summarize(a)["time_separated_audio_evidence"])

    def test_network_or_audio_failure_rejected(self):
        a = [
            {"transport_audio_prefix": True, "prefix_sha256": "a" * 64},
            {"transport_audio_prefix": False, "reason": "URLError"},
            {"transport_audio_prefix": True, "prefix_sha256": "b" * 64},
        ]
        self.assertFalse(summarize(a)["time_separated_audio_evidence"])

    def test_too_few_samples_do_not_pass(self):
        samples = [
            {"transport_audio_prefix": True, "prefix_sha256": x * 64}
            for x in ("a", "b")
        ]
        self.assertFalse(summarize(samples)["time_separated_audio_evidence"])


if __name__ == "__main__":
    unittest.main()
