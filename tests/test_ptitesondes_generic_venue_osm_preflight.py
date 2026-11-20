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

    def test_mirrored_leads_are_not_double_counted_as_sessions(self):
        event_a = lead("100")
        mirror = {**event_a, "collector":"opendatasoft-index"}
        second_session = lead("100", when="2026-12-13")
        records = [event_a, mirror, second_session]
        group = groups_for_review(records, DAY)[0]
        self.assertEqual(group["lead_count"], 3)
        self.assertEqual(group["unique_candidate_sessions"], 2)
        report = audit(records, DAY, live=False)
        self.assertEqual(report["unknown_venue_leads"], 3)
        self.assertEqual(report["unknown_candidate_sessions"], 2)
        self.assertEqual(report["duplicate_collector_or_repeated_leads"], 1)
        self.assertEqual(report["queried_venues"], 0)
        self.assertEqual(report["verified_venue_leads"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["public_writes"], 0)

    def test_rotation_repeats_nothing_within_cycle(self):
        groups = [{"key": ["c", str(i)]} for i in range(37)]
        for d in (date(2026, 11, 20), date(2026, 11, 21)):
            sample = private_rotation(groups, d)
            self.assertEqual(len(sample), 12)
            self.assertEqual(len({x["key"][1] for x in sample}), 12)

    def test_seven_private_batches_cover_79_venues_once_per_day(self):
        groups = [{"key": ["test", str(i)]} for i in range(79)]
        for today in (DAY, date(2026, 11, 21)):
            all_keys = []
            sizes = []
            for batch in range(7):
                selected = private_rotation(groups, today,
                                            batch_index=batch)
                sizes.append(len(selected))
                all_keys.extend(x["key"][1] for x in selected)
            self.assertEqual(sizes, [12, 12, 12, 12, 12, 12, 7])
            self.assertEqual(len(all_keys), len(set(all_keys)))
            self.assertEqual(set(all_keys),
                             {str(i) for i in range(79)})
            self.assertEqual(private_rotation(groups, today),
                             private_rotation(groups, today, batch_index=0))
            with self.assertRaises(ValueError):
                private_rotation(groups, today, batch_index=7)

    def test_batch_options_fail_closed_and_only_select_existing_venues(self):
        for malformed in (-1, True, 1.5, "1"):
            with self.assertRaises(ValueError):
                private_rotation([{}], DAY, batch_index=malformed)
        for malformed in (0, 13, True):
            with self.assertRaises(ValueError):
                private_rotation([{}], DAY, max_places=malformed)
        with self.assertRaises(ValueError):
            private_rotation([], DAY, batch_index=1)
        self.assertEqual(private_rotation([], DAY), [])
        self.assertEqual(len(private_rotation([{}]*5, DAY)), 5)

    def test_offline_batch_preview_is_read_only_and_reports_slot_counts(self):
        entries = [lead(str(10000+i), venue="Place "+str(i))
                   for i in range(25)]
        report0 = audit(entries, DAY, live=False, batch_index=0)
        report1 = audit(entries, DAY, live=False, batch_index=1)
        report2 = audit(entries, DAY, live=False, batch_index=2)
        self.assertEqual([r["selected_venues"] for r in
                          (report0, report1, report2)], [12,12,1])
        self.assertEqual([r["batch_count"] for r in
                          (report0, report1, report2)], [3,3,3])
        self.assertEqual([r["batch_index"] for r in
                          (report0, report1, report2)], [0,1,2])
        self.assertEqual(len({(r["city"],r["venue"]) for report in
                              (report0,report1,report2)
                              for r in report["records"]}), 25)
        for report in (report0,report1,report2):
            self.assertEqual(report["queried_venues"], 0)
            self.assertEqual(report["public_writes"], 0)
            self.assertFalse(report["publication_ready"])
        with self.assertRaises(ValueError):
            audit(entries, DAY, live=False, batch_index=3)

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

    def test_ign_bridge_keeps_verified_venues_and_events_at_zero(self):
        from ptitesondes_generic_venue_ign_corroboration import address_candidate
        osm = element()
        osm["tags"].update({
            "addr:housenumber": "12",
            "addr:street": "Rue des Lilas",
            "addr:postcode": "12345",
        })
        candidate = address_candidate(self.group, osm)
        self.assertIsNotNone(candidate)
        ban = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3.456, 45.123]},
            "properties": {
                "type": "housenumber", "score": 0.98,
                "city": candidate["city"], "postcode": candidate["postcode"],
                "housenumber": candidate["housenumber"],
                "label": candidate["address_query"],
            },
        }]}
        report = audit(
            self.leads, DAY, self.fetch,
            lambda xy: {"elements": [osm]}, live=True,
            ign_fetch=lambda c: ban,
        )
        self.assertEqual(report["independent_address_matches"], 1)
        self.assertEqual(report["leads_with_independent_address_hint"], 2)
        self.assertEqual(report["verified_venue_leads"], 0)
        self.assertFalse(report["official_venue_verified"])
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["publication_ready"])

    def test_full_private_place_evidence_never_enables_publisher(self):
        import json
        from ptitesondes_generic_venue_ign_corroboration import address_candidate
        osm = element()
        osm["tags"].update({
            "addr:housenumber": "12", "addr:street": "Rue des Lilas",
            "addr:postcode": "12345",
        })
        c = address_candidate(self.group, osm)
        ban = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3.456, 45.123]},
            "properties": {
                "type": "housenumber", "score": 0.98, "city": c["city"],
                "postcode": c["postcode"], "housenumber": c["housenumber"],
                "label": c["address_query"],
            },
        }]}
        venue = {"@type": "Place", "name": "Médiathèque des Étoiles",
                 "address": {"@type": "PostalAddress",
                             "streetAddress": "12 Rue des Lilas",
                             "postalCode": "12345",
                             "addressLocality": "Ville-test"}}
        html = ("<html><script type='application/ld+json'>"
                + json.dumps(venue) + "</script></html>")
        args = (self.leads, DAY, self.fetch)
        kwargs = dict(
            osm_fetch=lambda xy: {"elements": [osm]}, live=True,
            ign_fetch=lambda candidate: ban,
            official_page_get=lambda group: (
                "https://ville-test.fr/lieux/mediatheque", html),
        )
        untrusted = audit(*args, **kwargs)
        self.assertEqual(untrusted["official_identity_address_matches"], 0)
        approved = audit(*args, **kwargs,
                         approved_official_hosts=frozenset({"ville-test.fr"}))
        self.assertEqual(approved["official_identity_address_matches"], 1)
        self.assertEqual(approved["leads_with_private_official_place_evidence"], 2)
        self.assertEqual(approved["verified_venue_leads"], 0)
        self.assertFalse(approved["official_venue_verified"])
        self.assertFalse(approved["publication_ready"])
        self.assertEqual(approved["public_writes"], 0)

    def test_invalid_center_refused_before_provider(self):
        with self.assertRaises(ValueError):
            overpass_query(float("nan"), 3.4)


if __name__ == "__main__":
    unittest.main()
