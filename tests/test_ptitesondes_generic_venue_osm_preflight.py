"""Offline adversarial tests: private-only generic unknown-venue OSM hints."""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_generic_venue_osm_preflight import (
    audit, groups_for_review, private_rotation, source_center,
    osm_hints, inspect_group, overpass_query, MAX_ELEMENTS,
)

DAY = date(2026, 11, 20)


def lead(uid, venue="Médiathèque des Étoiles", city="Ville-test", when="2026-12-12"):
    return {
        "title": "Conte pour les familles", "collector": "openagenda-v2",
        "external_id": str(uid),
        "source_url": "https://openagenda.com/agenda-test/events/conte",
        "date_start": when, "date_end": when, "city": city,
        "venue": venue,
    }


def row(uid, lat=45.123, lng=3.456, venue="Médiathèque des Étoiles",
        city="Ville-test"):
    return {"uid": uid, "location_city": city, "location_name": venue,
            "location_coordinates": {"lat": lat, "lon": lng}}


def element(oid=11, name="Médiathèque des Étoiles", city="Ville-test",
            lat=45.123, lng=3.456):
    return {"type": "node", "id": oid,
            "lat": lat, "lon": lng,
            "tags": {"name": name, "addr:city": city}}


class GenericVenueOSMTests(unittest.TestCase):
    def setUp(self):
        self.leads = [lead("100"), lead("101"),
                      lead("102", "Jardin des familles")]
        self.group = groups_for_review(self.leads, DAY)[0]
        self.rows = {"100": row("100"), "101": row("101"),
                     "102": row("102", venue="Jardin des familles")}
        self.fetch = lambda uid: self.rows[uid]

    def test_groups_remove_already_known_and_disallowed(self):
        leads = self.leads + [lead("300", when="2026-10-01"), {"title": "legacy"}]
        groups = groups_for_review(leads, DAY)
        self.assertEqual(sum(g["lead_count"] for g in groups), 3)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["lead_count"], 2)
        self.assertEqual(set(groups[0]["uids"]), {"100", "101"})

    def test_rotation_repeats_nothing_within_cycle(self):
        groups = [{"key": ["c", str(i)]} for i in range(37)]
        for d in (date(2026, 11, 20), date(2026, 11, 21)):
            sample = private_rotation(groups, d)
            self.assertEqual(len(sample), 12)
            self.assertEqual(len({x["key"][1] for x in sample}), 12)

    def test_source_center_requires_exact_uid_and_identity(self):
        center, reason = source_center(self.group, self.fetch)
        self.assertEqual(center, (45.123, 3.456))
        self.assertIsNone(reason)
        bad = lambda uid: row("other")
        self.assertEqual(source_center(self.group, bad)[1],
                         "source_identity_mismatch")

    def test_source_center_disallows_contradictory_coordinates(self):
        badrows = {**self.rows, "101": row("101", lat=45.137)}
        result = source_center(self.group, lambda uid: badrows[uid])
        self.assertIsNone(result[0])
        self.assertEqual(result[1], "source_coordinates_disagree")

    def test_only_exact_osm_venue_and_city_and_distance(self):
        response = {"elements": [
            element(), element(12, name="Médiathèque des Étoiles Nord"),
            element(13, city="Autre-ville"),
            element(14, lat=45.144),
        ]}
        hints = osm_hints(self.group, (45.123, 3.456), response)
        self.assertEqual([h["osm_object_hint"] for h in hints], ["node/11"])
        self.assertFalse(hints[0]["gps_verified"])
        self.assertFalse(hints[0]["official_venue_verified"])

    def test_missing_city_is_never_an_official_city_proof(self):
        item = element()
        item["tags"].pop("addr:city")
        hints = osm_hints(self.group, (45.123, 3.456),
                          {"elements": [item]})
        self.assertEqual(len(hints), 1)
        self.assertFalse(hints[0]["city_tag_confirmed"])

    def test_reject_oversized_or_incomplete_provider(self):
        for payload in ({"elements": [{}] * MAX_ELEMENTS},
                        {"elements": [], "remark": "out of memory"},
                        {"not_elements": []}):
            with self.assertRaises(ValueError):
                osm_hints(self.group, (45.123, 3.456), payload)

    def test_one_hint_is_not_an_attestation(self):
        inspected = inspect_group(self.group, self.fetch,
                                  lambda xy: {"elements": [element()]})
        self.assertEqual(inspected["status"],
                         "single_osm_hint_requires_official_venue_and_address_proof")
        self.assertFalse(inspected["osm_candidates_unverified"][0]["gps_verified"])

    def test_two_independent_objects_require_review(self):
        inspected = inspect_group(
            self.group, self.fetch,
            lambda xy: {"elements": [element(), element(12)]})
        self.assertEqual(inspected["status"], "multiple_osm_hints_ambiguous")

    def test_provider_failure_fails_closed(self):
        def broken(x):
            raise OSError("transport")
        inspected = inspect_group(self.group, self.fetch, broken)
        self.assertEqual(inspected["status"],
                         "independent_provider_unavailable_or_incomplete")
        self.assertEqual(inspected["osm_candidates_unverified"], [])

    def test_no_network_in_default_preview_and_no_writes(self):
        untouched = [x.copy() for x in self.leads]
        blocked = Mock(side_effect=AssertionError("network forbidden"))
        report = audit(self.leads, DAY, blocked, blocked)
        self.assertEqual(report["unknown_venue_leads"], 3)
        self.assertEqual(report["unknown_unique_venues"], 2)
        self.assertEqual(report["queried_venues"], 0)
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["gps_verified"])
        self.assertEqual(self.leads, untouched)
        blocked.assert_not_called()

    def test_live_discovery_still_never_publishes(self):
        report = audit([lead("100")], DAY, self.fetch,
                       lambda c: {"elements": [element()]}, live=True)
        self.assertEqual(report["independent_hints"], 1)
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["records"][0]["lead_count"], 1)

    def test_invalid_center_refused_before_provider(self):
        with self.assertRaises(ValueError):
            overpass_query(float("nan"), 3.4)


if __name__ == "__main__":
    unittest.main()
