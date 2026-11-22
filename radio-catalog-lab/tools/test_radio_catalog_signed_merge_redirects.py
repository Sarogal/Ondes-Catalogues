#!/usr/bin/env python3
"""Public CI contract for signed permanent GO-ID merger redirects."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import unittest

from radio_catalog_guard import validate_catalog

SCHEMA = Path(__file__).resolve().parents[1] / "schemas/radio_catalog_v1.schema.json"


def station(i):
    return {
        "go_station_id": f"go-station-{i:06d}",
        "display_name": f"Test fictional radio {i}",
        "country_code": "FR",
        "genres": ["Metal"],
        "homepage": f"https://radio{i}.example.org/",
        "radio_browser_uuids": [{"uuid": f"legacy-{i}", "state": "historical"}],
        "legacy_aliases": [f"legacy-{i}"],
        "status": {"state": "active", "reason_code": None,
                   "changed_at": "2026-11-22T20:00:00Z"},
        "streams": [{"stream_id": "main", "url": f"https://radio{i}.example.org/audio",
                     "priority": 0, "protocol": "https", "codec": "MP3",
                     "bitrate_kbps": 192, "state": "verified"}],
        "logo": None,
        "editorial": {"admission_state": "approved",
                      "reviewed_at": "2026-11-22T20:00:00Z",
                      "evidence_refs": []},
    }


def tombstone(i, winner=None):
    row = {"go_station_id": f"go-station-{i:06d}",
           "legacy_aliases": [f"legacy-{i}"],
           "reason_code": "merged_into_station" if winner is not None else "retired_by_editorial_review",
           "retired_at": "2026-11-22T20:00:00Z"}
    if winner is not None:
        row["redirect_to"] = f"go-station-{winner:06d}"
    return row


def catalog(stations, *, sequence, tombstones=()):
    return {"schema_version": 1, "catalog_id": "grosses-ondes-radio",
            "release_sequence": sequence,
            "generated_at": "2026-11-22T20:00:00Z",
            "stations": stations, "tombstones": list(tombstones)}


class SignedIdentityRedirectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jsonschema import Draft202012Validator
        cls.schema = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))

    def valid(self, doc, previous=None):
        self.assertEqual(list(self.schema.iter_errors(doc)), [])
        self.assertEqual(validate_catalog(doc, mode="publish", previous=previous), [])

    def test_merge_go_id_keeps_old_uuid_and_go_identity_in_signed_tombstone(self):
        before = catalog([station(1), station(2)], sequence=1)
        after = catalog([station(1)], sequence=2, tombstones=[tombstone(2, 1)])
        self.valid(before)
        self.valid(after, previous=before)
        self.assertEqual(after["tombstones"][0]["legacy_aliases"], ["legacy-2"])

    def test_no_redirect_to_unknown_or_retired_or_self(self):
        before = catalog([station(1), station(2)], sequence=1)
        for target in [2, 3]:
            next_ = catalog([station(1)], sequence=2, tombstones=[tombstone(2, target)])
            self.assertTrue(validate_catalog(next_, mode="publish", previous=before))
        wrong = catalog([station(1)], sequence=2, tombstones=[tombstone(2, 1)])
        wrong["tombstones"][0]["reason_code"] = "retired_by_editorial_review"
        self.assertTrue(validate_catalog(wrong, mode="publish", previous=before))

    def test_previous_redirect_cannot_be_retargeted_to_unrelated_radio(self):
        v1 = catalog([station(1), station(2), station(3)], sequence=1)
        v2 = catalog([station(1), station(3)], sequence=2, tombstones=[tombstone(2, 1)])
        self.valid(v2, previous=v1)
        hijack = catalog([station(1), station(3)], sequence=3, tombstones=[tombstone(2, 3)])
        self.assertTrue(any("hijacked" in e for e in
                            validate_catalog(hijack, mode="publish", previous=v2)))
        v3 = catalog([station(3)], sequence=3,
                     tombstones=[tombstone(1, 3), tombstone(2, 3)])
        self.valid(v3, previous=v2)

    def test_alias_loss_remains_forbidden_even_when_go_id_has_redirect(self):
        v1 = catalog([station(1), station(2)], sequence=1)
        v2 = catalog([station(1)], sequence=2, tombstones=[tombstone(2, 1)])
        v2["tombstones"][0]["legacy_aliases"] = []
        self.assertTrue(any("historical alias lost" in e for e in
                            validate_catalog(v2, mode="publish", previous=v1)))

    def test_unrelated_retired_tombstone_is_not_a_redirect(self):
        v1 = catalog([station(1), station(2)], sequence=1)
        v2 = catalog([station(1)], sequence=2, tombstones=[tombstone(2)])
        self.valid(v2, previous=v1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
