"""Fail-closed, data-driven trust registry for previously unlisted concert venues.

This test uses synthetic domains and isolated files; no private signatures,
network requests, official website claims or production changes are involved.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from scripts import concerts_cloud_sync as sync

DAY = dt.date(2026, 11, 16)
IDENT = "synthetic-trusted-stage-one"
SPEC = {
    "venue": {
        "id": IDENT,
        "name": "Salle Test de confiance",
        "address": "1 rue du Test",
        "postalCode": "75001",
        "city": "Commune de Test",
        "department": "75",
        "region": "Île-de-France",
        "latitude": 48.86,
        "longitude": 2.33,
        "geoPrecision": "point indépendant à vérifier",
        "geoSource": "https://map.example.net/place/stage-one",
    },
    "officialUrl": "https://venue.example.org/access",
    "locationUrl": "https://map.example.net/place/stage-one",
    "locationProofType": "openstreetmap-venue-node",
}


def approval():
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DAY.isoformat(),
        "venue": copy.deepcopy(SPEC["venue"]),
        "officialEvidence": [
            {
                "url": SPEC["officialUrl"],
                "proofType": "official-venue-address",
                "checkedAt": DAY.isoformat(),
                "checkedFields": ["name", "address", "postalCode", "city"],
            },
            {
                "url": SPEC["locationUrl"],
                "proofType": SPEC["locationProofType"],
                "checkedAt": DAY.isoformat(),
                "checkedFields": ["venueName", "coordinates"],
            },
        ],
    }


class ReviewableVenueRegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "reviewed.json"
        patcher = mock.patch.object(sync, "REVIEWED_VENUE_SPECS_PATH", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        sync.read_reviewed_venue_specs.cache_clear()
        self.addCleanup(sync.read_reviewed_venue_specs.cache_clear)

    def registry(self, venues):
        self.file.write_text(json.dumps({
            "schema": "grossesondes.concert.reviewed-venue-specs.v1",
            "venues": venues,
        }), encoding="utf-8")
        sync.read_reviewed_venue_specs.cache_clear()

    def test_unlisted_private_approval_cannot_self_register_venue(self):
        self.registry({})
        with self.assertRaisesRegex(ValueError, "non agréée"):
            sync.validate_venue_approval(approval(), DAY)
        self.assertEqual(sync.read_reviewed_venue_specs(), {})

    def test_two_independent_signatures_are_needed_for_reviewed_venue(self):
        self.registry({IDENT: SPEC})
        self.assertEqual(sync.validate_venue_approval(approval(), DAY),
                         SPEC["venue"])
        for key, fn in (
            ("wrong-coordinates", lambda r: r["venue"].update(latitude=47.0)),
            ("spoofed-reviewer", lambda r: r.update(reviewedBy="candidate")),
            ("wrong-official-url", lambda r: r["officialEvidence"][0].update(
                url="https://candidate.example.org/not-official")),
            ("wrong-geo-url", lambda r: r["officialEvidence"][1].update(
                url="https://candidate.example.org/not-independent")),
            ("missing-address-proof", lambda r: r["officialEvidence"][0].update(
                checkedFields=["name", "city"])),
            ("undated-check", lambda r: r["officialEvidence"][0].update(
                checkedAt="2020-01-01")),
            ("extra-proof", lambda r: r["officialEvidence"].append({
                "url": "https://unknown.example.org",
                "proofType": "generic",
            })),
        ):
            with self.subTest(key=key):
                mutated = approval()
                fn(mutated)
                with self.assertRaises(ValueError):
                    sync.validate_venue_approval(mutated, DAY)

    def test_registry_schema_https_geolocation_and_legacy_collision_are_strict(self):
        for key, fn in (
            ("malformed-schema", lambda v: {"schema": "wrong", "venues": v}),
            ("wrong-key", lambda v: {"schema": "grossesondes.concert.reviewed-venue-specs.v1", "bad": v}),
        ):
            with self.subTest(key=key):
                self.file.write_text(json.dumps(fn({IDENT: SPEC})), encoding="utf-8")
                sync.read_reviewed_venue_specs.cache_clear()
                with self.assertRaises(ValueError):
                    sync.read_reviewed_venue_specs()

        for key, fn in (
            ("unsigned-http", lambda s: s.update(officialUrl="http://venue.example.org/access")),
            ("metadata-override", lambda s: s.update(unknownField="attack")),
            ("GPS-lie", lambda s: s["venue"].update(latitude=181.0)),
            ("geo-source-mismatch", lambda s: s["venue"].update(geoSource="https://other.example.org/map")),
            ("identity-mismatch", lambda s: s["venue"].update(id="other")),
            ("extra-location-field", lambda s: s["venue"].update(hidden="value")),
        ):
            with self.subTest(key=key):
                spec = copy.deepcopy(SPEC)
                fn(spec)
                self.registry({IDENT: spec})
                with self.assertRaises(ValueError):
                    sync.read_reviewed_venue_specs()

        legacy_id = next(iter(sync.PILOT_VENUES))
        self.registry({legacy_id: sync.PILOT_VENUES[legacy_id]})
        with self.assertRaises(ValueError):
            sync.read_reviewed_venue_specs()

    def test_nonlisted_venue_enters_catalogue_only_after_both_approvals(self):
        self.registry({IDENT: SPEC})
        baseline = json.loads(sync.REFERENCE.read_text(encoding="utf-8"))
        private = {
            "schema": sync.SCHEMA, "approvals": [],
            "venueApprovals": [approval()],
        }
        after, stats = sync.merge(baseline, baseline, private, DAY)
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(stats["newEvents"], 0)
        self.assertEqual(stats["held"], [])
        self.assertEqual(after["venues"][-1], SPEC["venue"])
        again, count = sync.merge(baseline, after, private, DAY)
        self.assertEqual(again, after)
        self.assertEqual(count["newVenues"], 0)
        self.assertEqual(count["alreadyRegisteredVenues"], 1)
        sync.protect_reference(baseline, again)


if __name__ == "__main__":
    unittest.main()
