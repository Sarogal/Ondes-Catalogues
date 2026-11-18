"""Adversarial, offline-only checks for three separately curated MPT venues."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_mpt_independent_geo_pilot import (
    PILOT_VENUES, REGISTRY_KEYS, reviewed_pilot_records,
    validate_curated_registry, review_exact_venue_name,
    independent_geo_recheck, geo_review_report,
    national_preflight_venue_registry,
)

EXTERNAL_SCORES = (0.9768809090909089, 0.9724745454545455,
                   0.9704199999999998, 0.9732336363636362,
                   0.9768809090909089, 0.9704199999999998,
                   0.9724745454545455)


def geocode(row, score=0.975, feature_type="housenumber"):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point",
                     "coordinates": [row["lng"], row["lat"]]},
        "properties": {
            "label": row["address_label"], "type": feature_type,
            "score": score, "city": row["city"], "postcode": row["postcode"],
        },
    }]}


class ReviewedMptVenueTests(unittest.TestCase):
    def setUp(self):
        self.records = reviewed_pilot_records()

    def test_seven_pinned_municipal_and_independent_geo_sources(self):
        self.assertTrue(validate_curated_registry(self.records))
        self.assertEqual(len(self.records), 7)
        self.assertEqual({r["venue"] for r in self.records}, {
            "Maison pour tous Mélina Mercouri",
            "Maison pour tous Frida Kahlo",
            "Maison pour tous Albert Dubout",
            "Maison pour tous Michel Colucci",
            "Maison pour tous Marie Curie",
            "Maison pour tous L'Escoutaïre",
            "Maison pour tous François Villon",
        })
        for r in self.records:
            with self.subTest(venue=r["venue"]):
                self.assertTrue(r["institutional_url"].startswith(
                    "https://mpt.montpellier.fr/evenement/"))
                self.assertTrue(r["geo_source_url"].startswith(
                    "https://data.geopf.fr/geocodage/search?"))
                self.assertEqual(r["city"], "Montpellier")
                self.assertEqual(r["department"], "Hérault")

    def test_immutable_defensive_copies_and_published_catalogue_untouched(self):
        self.records[0]["lat"] = 0
        self.assertNotEqual(self.records[0]["lat"], PILOT_VENUES[0]["lat"])
        self.assertTrue(validate_curated_registry())

    def test_live_shaped_exact_housenumber_matches(self):
        for row, score in zip(self.records, EXTERNAL_SCORES):
            with self.subTest(venue=row["venue"]):
                self.assertTrue(independent_geo_recheck(
                    row, geocode(row, score=score)))

    def test_street_centroid_and_low_confidence_never_accepted(self):
        for row in self.records:
            self.assertFalse(independent_geo_recheck(
                row, geocode(row, feature_type="street")))
            self.assertFalse(independent_geo_recheck(
                row, geocode(row, score=0.949)))
            self.assertFalse(independent_geo_recheck(
                row, geocode(row, score=1.01)))

    def test_moved_building_wrong_label_or_city_is_held(self):
        for row in self.records:
            moved = geocode(row)
            moved["features"][0]["geometry"]["coordinates"][0] += 0.005
            self.assertFalse(independent_geo_recheck(row, moved))
            wrong_label = geocode(row)
            wrong_label["features"][0]["properties"]["label"] += " annexe"
            self.assertFalse(independent_geo_recheck(row, wrong_label))
            wrong_city = geocode(row)
            wrong_city["features"][0]["properties"]["city"] = "Lattes"
            self.assertFalse(independent_geo_recheck(row, wrong_city))
            wrong_zip = geocode(row)
            wrong_zip["features"][0]["properties"]["postcode"] = "99999"
            self.assertFalse(independent_geo_recheck(row, wrong_zip))

    def test_duplicate_exact_geo_results_are_ambiguous(self):
        for row in self.records:
            duplicate = geocode(row)
            duplicate["features"].append(deepcopy(duplicate["features"][0]))
            self.assertFalse(independent_geo_recheck(row, duplicate))

    def test_nonfinite_wrong_shape_and_missing_geo_fail_closed(self):
        row = self.records[0]
        for bad in (None, [], {}, {"features": None}, {"features": "x"},
                    {"features": [{}]}, {"features": [{}] * 11}):
            self.assertFalse(independent_geo_recheck(row, bad))
        invalid = geocode(row)
        invalid["features"][0]["geometry"]["coordinates"] = [float("nan"), 0]
        self.assertFalse(independent_geo_recheck(row, invalid))

    def test_exact_name_and_city_only_without_auto_aliases(self):
        row = self.records[0]
        found = review_exact_venue_name("Montpellier", "Maison pour tous Mélina Mercouri")
        self.assertEqual(found["venue_key"], row["venue_key"])
        self.assertIsNone(review_exact_venue_name(
            "Lattes", "Maison pour tous Mélina Mercouri"))
        self.assertIsNone(review_exact_venue_name(
            "Montpellier", "Maison pour tous Mélina Mercouri annexe"))
        self.assertIsNone(review_exact_venue_name(
            "Montpellier", "Maison pour tous inconnue"))
        self.assertIsNone(review_exact_venue_name(
            "Montpellier", "842 rue de la Vieille Poste"))

    def test_registry_conflict_or_unreviewed_pointers_are_refused(self):
        invalid = reviewed_pilot_records()
        invalid[1]["venue_key"] = invalid[0]["venue_key"]
        self.assertFalse(validate_curated_registry(invalid))
        invalid = reviewed_pilot_records()
        invalid[0]["institutional_url"] = (
            "https://mpt.montpellier.fr.evil.test/evenement/foo")
        self.assertFalse(validate_curated_registry(invalid))
        invalid = reviewed_pilot_records()
        invalid[0]["geo_source_url"] = (
            "https://data.geopf.fr.evil.test/geocodage/search"
            "?q=842%20Rue%20de%20la%20Vieille%20Poste%2034000%20Montpellier&limit=2")
        self.assertFalse(validate_curated_registry(invalid))
        invalid = reviewed_pilot_records()
        invalid[0]["address_label"] = "unverified"
        self.assertFalse(validate_curated_registry(invalid))

    def test_curated_registry_schema_allows_more_buildings_without_new_parser(self):
        # Structural-only synthetic extension: NOT a newly approved real venue.
        example = deepcopy(self.records[0])
        example["venue_key"] = "mpt-synthetic-venue-montpellier"
        example["venue"] = "Maison pour tous Synthétique"
        example["address_label"] = "44 Rue des Tests 34000 Montpellier"
        example["institutional_url"] = (
            "https://mpt.montpellier.fr/evenement/synthetic-example")
        example["geo_source_url"] = (
            "https://data.geopf.fr/geocodage/search?"
            "q=44%20Rue%20des%20Tests%2034000%20Montpellier&limit=2")
        expanded = reviewed_pilot_records() + [example]
        self.assertTrue(validate_curated_registry(expanded))
        self.assertIsNone(review_exact_venue_name(
            "Montpellier", "Maison pour tous Synthétique"))
        self.assertEqual(review_exact_venue_name(
            "Montpellier", "Maison pour tous Synthétique",
            records=expanded)["venue_key"], example["venue_key"])

    def test_private_free_anonymous_report_and_no_publication(self):
        responses = {row["venue_key"]: geocode(row) for row in self.records}
        report = geo_review_report(self.records, responses)
        self.assertEqual(report["curated_venues_checked"], 7)
        self.assertEqual(report["exact_external_housenumber_matches"], 7)
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["publisher_connected"])
        self.assertEqual(report["human_approvals"], 0)
        payload = json.dumps(report)
        for value in ("Mélina", "Kahlo", "Dubout", "Montpellier",
                      "source_url", "events", "additions", "patch",
                      "3.907746", "43.614655"):
            self.assertNotIn(value, payload)

    def test_missing_or_partial_recheck_does_not_look_successful(self):
        responses = {row["venue_key"]: geocode(row) for row in self.records}
        with self.assertRaisesRegex(ValueError, "incomplete_exact"):
            geo_review_report(self.records, {
                self.records[0]["venue_key"]: geocode(self.records[0])})
        responses[self.records[1]["venue_key"]] = geocode(
            self.records[1], feature_type="street")
        r = geo_review_report(self.records, responses)
        self.assertEqual(r["exact_external_housenumber_matches"], 6)
        self.assertEqual(r["held_for_external_geo_review"], 1)
        self.assertFalse(r["publication_ready"])

    def test_preflight_venue_schema_only_not_event_admission(self):
        refs = national_preflight_venue_registry()
        self.assertEqual(len(refs), 7)
        for ref in refs:
            self.assertEqual(set(ref), REGISTRY_KEYS)
            for forbidden in ("date_start", "title", "source_url",
                              "age_min", "age_max", "admitted", "approved"):
                self.assertNotIn(forbidden, ref)


if __name__ == "__main__":
    unittest.main()
