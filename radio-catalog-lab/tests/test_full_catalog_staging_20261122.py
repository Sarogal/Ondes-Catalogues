#!/usr/bin/env python3
"""Real 320-station staging invariants on public CI, WITHOUT public deployment.

The full candidate is inert: it is NOT a release and NOT current.json.
The existing TEST generation 4 is authenticated before trusting its IDs.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit
import unittest

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "radio-catalog-lab/full-staging"
TEST = ROOT / "grossesondes/radio-test-apk"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class FullCatalogStagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.draft = read(STAGING / "candidate-20261122.json")
        cls.coverage = read(STAGING / "coverage-20261122.json")
        cls.pointer = read(TEST / "current.json")
        cls.previous_file = TEST / cls.pointer["content_path"]
        cls.predecessor = read(cls.previous_file)

    def test_signed_test_v4_pointer_matches_immutable_payload(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        p = self.pointer
        payload = self.previous_file.read_bytes()
        self.assertEqual(p["release_sequence"], 4)
        self.assertEqual(p["signature"]["algorithm"], "Ed25519")
        self.assertEqual(p["content_length"], len(payload))
        self.assertEqual(p["content_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(p["content_path"], f"releases/{p['content_sha256']}.json")
        public = base64.b64decode((TEST / "TEST_PUBLIC_KEY.b64").read_text().strip())
        fields = ["GO-RADIO-CATALOG-POINTER-V1", str(p["schema_version"]),
                  p["catalog_id"], str(p["release_sequence"]),
                  p["published_at"], p["content_sha256"], str(p["content_length"]),
                  p["content_path"], p["signature"]["key_id"], ""]
        message = "\n".join(fields).encode("utf-8")
        Ed25519PublicKey.from_public_bytes(public).verify(
            base64.b64decode(p["signature"]["signature_base64"]), message)

    def test_candidate_is_inert_sequence_5_not_published(self):
        self.assertEqual(self.draft["release_sequence"], 5)
        self.assertEqual(self.predecessor["release_sequence"], 4)
        self.assertFalse(self.coverage["ready_to_publish"])
        self.assertFalse(self.coverage["signed_replacement_generated"])
        self.assertEqual(self.coverage["status"], "STAGING_ONLY_NOT_SIGNED")

    def test_all_legacy_active_radios_are_included_without_double_entries(self):
        rows = self.draft["stations"]
        self.assertEqual(len(rows), 320)
        self.assertEqual(sum(s["status"]["state"] == "active" for s in rows), 318)
        self.assertEqual(sum(s["status"]["state"] == "quarantined" for s in rows), 2)
        ids = [s["go_station_id"] for s in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.coverage["source_v64_stations"], 310)
        self.assertEqual(self.coverage["source_v64_streams"], 345)

    def test_hardradio_one_station_two_formats_and_preserved_favorites(self):
        hs = [s for s in self.draft["stations"] if "hardradio" in s["display_name"].lower()]
        self.assertEqual(len(hs), 1)
        st = hs[0]
        self.assertEqual(st["go_station_id"], "go-station-000146")
        self.assertEqual(set(st["legacy_aliases"]),
            {"9609c009-0601-11e8-ae97-52543be04c81",
             "960b1fda-0601-11e8-ae97-52543be04c81"})
        self.assertEqual({(x["codec"], x["bitrate_kbps"]) for x in st["streams"]},
                         {("MP3", 128), ("AAC+", 64)})

    def test_all_test_v4_identities_aliases_and_verified_logo_preserved(self):
        new = {s["go_station_id"]: s for s in self.draft["stations"]}
        for existing in self.predecessor["stations"]:
            candidate = new[existing["go_station_id"]]
            self.assertEqual(candidate, existing)
        self.assertEqual(sum(bool(s.get("logo")) for s in new.values()), 1)

    def test_aliases_unique_and_27_gap_uuids_accounted_for(self):
        all_aliases = [(x, s["go_station_id"]) for s in self.draft["stations"]
                       for x in s["legacy_aliases"]]
        owners = dict(all_aliases)
        self.assertEqual(len(owners), len(all_aliases))
        self.assertEqual(len(owners), 363)
        self.assertEqual(self.coverage["source_v64_aliases"], 346)
        self.assertEqual(len(self.coverage["new_aliases_from_direct_stream_match"]), 8)
        self.assertEqual(len(self.coverage["new_station_rows"]), 9)
        self.assertEqual(len(self.coverage["unresolved_uuids"]), 10)
        self.assertEqual(8 + 9 + 10, 27)
        for row in self.coverage["new_aliases_from_direct_stream_match"]:
            self.assertEqual(owners[row["uuid"]], row["go_station_id"])
        for row in self.coverage["new_station_rows"]:
            self.assertEqual(owners[row["uuid"]], row["go_station_id"])
        for row in self.coverage["unresolved_uuids"]:
            self.assertNotIn(row["uuid"], owners)

    def test_never_claim_unverified_streams_or_invent_logos(self):
        states = [stream["state"] for st in self.draft["stations"]
                  for stream in st["streams"]]
        self.assertEqual(len(states), 358)
        self.assertEqual(states.count("verified"), 2)
        self.assertEqual(states.count("candidate_verified"), 2)
        self.assertEqual(states.count("candidate"), 354)
        self.assertEqual(self.coverage["verified_streams"], 2)
        self.assertEqual(self.coverage["sha_qualified_logos"], 1)

    def test_public_urls_non_private_and_no_embedded_credentials(self):
        for st in self.draft["stations"]:
            for stream in st["streams"]:
                url = urlsplit(stream["url"])
                self.assertIn(url.scheme, ("http", "https"))
                self.assertIsNotNone(url.hostname)
                self.assertIsNone(url.username)
                self.assertIsNone(url.password)
                host = url.hostname.lower().rstrip(".")
                self.assertNotIn(host, ("localhost", "localhost.localdomain"))
                self.assertFalse(host.endswith(".local"))
                try:
                    addr = ipaddress.ip_address(host)
                except ValueError:
                    self.assertIn(".", host)
                else:
                    self.assertTrue(addr.is_global)

    def test_no_missing_historical_uuids_are_silently_deleted(self):
        rows = self.coverage["unresolved_uuids"]
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({s["uuid"] for s in rows}), 10)
        for row in rows:
            self.assertEqual(row["reason"], "missing_from_radio_browser_20261115")
            self.assertIn("recheck", row["action"])
        self.assertEqual(len(self.coverage["same_stream_different_names_need_name_review"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
