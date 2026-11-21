#!/usr/bin/env python3
"""Verify the EXACT signed Android TEST fixture; no network, no publication."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from radio_catalog_release_packager import (
    read_public_key, verify_bundle, strict_json,
)

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "grossesondes" / "radio-test-apk"


class SignedApkQuarantineFixtureTests(unittest.TestCase):
    def test_ed25519_three_sequences_and_nonplayable_quarantine(self):
        key = read_public_key(LAB / "TEST_PUBLIC_KEY.b64")
        previous = None
        seen_ids = set()
        for n in (1, 2, 3):
            pointer_path = (
                LAB / "current.json" if n == 1 else
                LAB / "pending" / f"test-current-v{n}.json"
            )
            raw_pointer = pointer_path.read_bytes()
            pointer = strict_json(raw_pointer, maximum=16*1024)
            self.assertEqual(pointer["release_sequence"], n)
            self.assertEqual(pointer["signature"]["key_id"],
                             "go-apk-test-20261121")
            body = (LAB / pointer["content_path"]).read_bytes()
            verified = verify_bundle(raw_pointer, body, key, previous=previous)
            self.assertEqual(verified.sequence, n)

            doc = json.loads(body)
            ids = {s["go_station_id"] for s in doc["stations"]}
            self.assertTrue(ids.issuperset(seen_ids), "No historical GO ID loss")
            seen_ids = ids
            for item in doc["stations"]:
                self.assertEqual(item["status"]["state"], "quarantined")
                self.assertEqual(item["status"]["reason_code"],
                                 "synthetic_diagnostic_not_for_playback")
                self.assertIsNone(item["logo"])
                self.assertTrue(all(
                    s["state"] != "verified" for s in item["streams"]
                ), "Never activate synthetic audio")

            previous = doc

    def test_pointer_one_remains_active_until_manual_test_promote(self):
        pointer = json.loads((LAB / "current.json").read_text(encoding="utf-8"))
        self.assertEqual(pointer["release_sequence"], 1)

    def test_pending_versions_mean_candidate_url_change_not_playback(self):
        p1 = json.loads((LAB / "current.json").read_text(encoding="utf-8"))
        p2 = json.loads((LAB / "pending/test-current-v2.json").read_text())
        c1 = json.loads((LAB / p1["content_path"]).read_text())
        c2 = json.loads((LAB / p2["content_path"]).read_text())
        self.assertEqual(len(c1["stations"]), 1)
        self.assertEqual(len(c2["stations"]), 2)
        self.assertNotEqual(
            c1["stations"][0]["streams"][0]["url"],
            c2["stations"][0]["streams"][0]["url"],
        )
        self.assertFalse(
            any(s["status"]["state"] == "active" for s in c2["stations"])
        )


if __name__ == "__main__":
    unittest.main()
