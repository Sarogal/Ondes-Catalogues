#!/usr/bin/env python3
"""Offline safety tests for unbounded discovery intake (zero network)."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from probe_open_radio_candidates import (
    CandidateError, audio_magic, evaluate, public_https, validate_input,
)

MANIFEST = (
    TOOLS.parents[1] / "grossesondes" / "radio-test-apk" /
    "candidates" / "punk_official_sources.json"
)


class OpenRadioCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_real_official_sources_are_candidates_only(self):
        rows = validate_input(self.document)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["status"] == "candidate" for row in rows))
        self.assertTrue(all(row["genres"] == ["Punk"] for row in rows))
        report = evaluate(self.document, allow_network=False)
        self.assertFalse(report["publication_allowed"])
        self.assertFalse(report["signed_release_generated"])
        self.assertEqual(report["candidate_count"], 2)
        for item in report["candidates"]:
            self.assertEqual(item["editorial_state"], "candidate")
            self.assertTrue(item["requires_audio_continuity_review"])
            self.assertTrue(item["requires_logo_byte_sha_review"])
            self.assertTrue(all(
                not s["transport_audio_prefix"] for s in item["transport"]
            ))

    def test_no_closed_name_or_uuid_allowlist(self):
        doc = deepcopy(self.document)
        novel = deepcopy(doc["candidates"][0])
        novel["candidate_id"] = "new-radio-never-seen-2027"
        novel["name"] = "Undiscovered Punk Fusion Radio"
        novel["known_legacy_ids"] = []
        novel["official_station_page"] = "https://new-radio.example.org/program"
        novel["official_stream_evidence"] = "https://new-radio.example.org/streams"
        novel["streams"] = [{
            "codec": "MP3", "bitrate_kbps": 0,
            "url": "https://cdn.new-radio.example.org/punk"
        }]
        doc["candidates"].append(novel)
        self.assertEqual(len(validate_input(doc)), 3)

    def test_rejects_duplicate_legacy_alias(self):
        doc = deepcopy(self.document)
        doc["candidates"][1]["known_legacy_ids"] = (
            doc["candidates"][0]["known_legacy_ids"][:]
        )
        with self.assertRaises(CandidateError):
            validate_input(doc)

    def test_rejects_private_redirect_targets(self):
        for url in [
            "http://radio.example.org/audio", "https://127.0.0.1/audio",
            "https://10.0.0.12/stream", "https://localhost/admin",
            "https://metadata.internal/credentials",
            "https://radio.example.org:444/stream", "file:///etc/passwd",
            "https://person:password@radio.example.org/stream",
            "https://radio.example.org/stream#fragment",
        ]:
            with self.subTest(url=url):
                self.assertFalse(public_https(url))
        self.assertTrue(public_https("https://example-radio.fr/live"))

    def test_rejects_unreviewed_becoming_verified(self):
        doc = deepcopy(self.document)
        doc["publication_allowed"] = True
        with self.assertRaises(CandidateError):
            validate_input(doc)
        doc = deepcopy(self.document)
        doc["candidates"][0]["status"] = "active"
        with self.assertRaises(CandidateError):
            validate_input(doc)
        doc = deepcopy(self.document)
        doc["candidates"][0]["logo_candidates"] = [{
            "url": "https://img.radio.example.org/logo.png", "state": "verified"
        }]
        with self.assertRaises(CandidateError):
            validate_input(doc)

    def test_audio_magic_refuses_non_audio(self):
        self.assertFalse(audio_magic(b"<html>" + b"x" * 500, "MP3"))
        self.assertFalse(audio_magic(b"not a stream" * 100, "AAC"))
        self.assertTrue(audio_magic(b"ID3" + b"x" * 256, "MP3"))
        self.assertTrue(audio_magic(b"\xff\xfb" + b"x" * 256, "MP3"))
        self.assertTrue(audio_magic(b"\xff\xf1" + b"x" * 256, "AAC"))
        self.assertTrue(audio_magic(b"OggS" + b"x" * 256, "OGG"))


if __name__ == "__main__":
    unittest.main()
