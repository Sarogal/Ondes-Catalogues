#!/usr/bin/env python3
"""Verify TEST-only pending signed Punk generation 4, never activate pointer."""
import json
from pathlib import Path
import unittest

from radio_catalog_release_packager import (
    read_public_key, verify_bundle, strict_json,
)

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "grossesondes" / "radio-test-apk"
DIGEST3 = "1fb8a0833af94e6da88704279bfadaa87f279cac0cffc97418d4ccdedbf364d7"
DIGEST4 = "f2add6a89c3566cc33d190cb6af834bc8cb1cbdce768d028c49a9dcfd5ec1db7"
LOGO_ROCK_SHA = "715d7a4cee2db4c3852ccd3336fcabbffd9ad727981538fe2ce43ec567375331"
BOB_ID = "9618c802-0601-11e8-ae97-52543be04c81"
ROCK_ID = "960c4c2a-0601-11e8-ae97-52543be04c81"


class SignedRealPunkPendingTests(unittest.TestCase):
    def test_pending_signatures_history_and_sha(self):
        key = read_public_key(LAB / "TEST_PUBLIC_KEY.b64")
        v3 = strict_json((LAB / f"releases/{DIGEST3}.json").read_bytes(),
                         maximum=10*1024*1024)
        pointer = (LAB / "pending/test-current-v4.json").read_bytes()
        content = (LAB / f"releases/{DIGEST4}.json").read_bytes()
        verified = verify_bundle(pointer, content, key, previous=v3)
        self.assertEqual(verified.sequence, 4)
        self.assertEqual(verified.digest, DIGEST4)

        v4 = json.loads(content)
        self.assertEqual(len(v4["stations"]), 4)
        self.assertEqual(v4["stations"][:2], v3["stations"])
        active = [x for x in v4["stations"] if x["status"]["state"] == "active"]
        self.assertEqual(len(active), 2)
        by_alias = {uuid: station for station in active
                    for uuid in station["legacy_aliases"]}
        self.assertEqual(set(by_alias), {BOB_ID, ROCK_ID})
        self.assertEqual({s["genres"][0] for s in active}, {"Punk"})
        for station in active:
            self.assertEqual(station["editorial"]["admission_state"], "approved")
            self.assertGreater(len(station["editorial"]["evidence_refs"]), 1)
            self.assertEqual(station["streams"][0]["state"], "verified")
            self.assertTrue(station["streams"][0]["url"].startswith("https://"))
            self.assertEqual(station["streams"][1]["state"], "candidate_verified")

        self.assertIsNone(by_alias[BOB_ID]["logo"],
                          "Do not claim generic BOB network logo is Punk-specific")
        rock_logo = by_alias[ROCK_ID]["logo"]
        self.assertEqual(rock_logo["sha256"], LOGO_ROCK_SHA)
        self.assertEqual(rock_logo["byte_size"], 484148)
        self.assertEqual((rock_logo["width"], rock_logo["height"]), (2000,2000))
        self.assertEqual(rock_logo["mime_type"], "image/jpeg")

    def test_active_pointer_is_only_authorized_v1_or_v4(self):
        # Explicit owner approval 21/11: allow activation of pending v4 ONLY on
        # the isolated diagnostic branch; never a production/main release.
        active = json.loads((LAB / "current.json").read_text(encoding="utf-8"))
        self.assertIn(active["release_sequence"], (1, 4))
        if active["release_sequence"] == 4:
            self.assertEqual(active["content_sha256"], DIGEST4)
            self.assertEqual(
                (LAB / "current.json").read_bytes(),
                (LAB / "pending/test-current-v4.json").read_bytes(),
            )
        else:
            self.assertNotEqual(active["content_sha256"], DIGEST4)


if __name__ == "__main__":
    unittest.main()
