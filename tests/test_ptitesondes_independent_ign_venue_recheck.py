"""Adversarial, fully offline tests for the generic independent IGN recheck."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from venue_registry import VENUES
from ptitesondes_independent_ign_venue_recheck import (
    recheck_ign, reviewed_search, redacted_report,
)

TARGETS = (
    ("Villeurbanne", "Studio 24"),
    ("Rouen", "Bibliothèque Aretha-Franklin"),
    ("Rouen", "Bibliothèque Simone de Beauvoir"),
    ("Roubaix", "Médiathèque de Roubaix - La Grand-Plage"),
)


def venue(city="Villeurbanne", name="Studio 24"):
    matches = [
        v for v in VENUES if v["city"] == city and name in v["aliases"]
    ]
    if len(matches) != 1:
        raise AssertionError("test fixture city/venue no longer uniquely reviewed")
    return deepcopy(matches[0])


def verified_feature(record):
    query, postcode, house = reviewed_search(record)
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point", "coordinates": [record["lng"], record["lat"]],
        },
        "properties": {
            "type": "housenumber", "label": query, "score": 0.975,
            "housenumber": house, "postcode": postcode, "city": record["city"],
        },
    }


def response(record):
    return {"type": "FeatureCollection", "features": [verified_feature(record)]}


class IndependentIgnRecheckTests(unittest.TestCase):
    def test_all_four_pinned_venues_pass_exact_housenumber(self):
        for city, name in TARGETS:
            with self.subTest(city=city, venue=name):
                record = venue(city, name)
                self.assertIsNotNone(reviewed_search(record))
                self.assertEqual(recheck_ign(record, response(record)),
                                 (True, "external_housenumber_reconfirmed"))

    def test_street_level_and_low_score_fail(self):
        record = venue()
        for change in ({"type": "street"}, {"score": 0.949}):
            doc = response(record)
            doc["features"][0]["properties"].update(change)
            self.assertFalse(recheck_ign(record, doc)[0])

    def test_city_postcode_housenumber_and_label_must_be_exact(self):
        record = venue()
        for patch in ({"city": "Autreville"}, {"postcode": "99999"},
                      {"housenumber": "25"},
                      {"label": "24 Rue de la Mairie 69100 Villeurbanne"}):
            doc = response(record)
            doc["features"][0]["properties"].update(patch)
            self.assertFalse(recheck_ign(record, doc)[0])

    def test_ambiguous_duplicate_and_wrong_coordinate_fail(self):
        record = venue()
        doc = response(record)
        doc["features"].append(deepcopy(doc["features"][0]))
        self.assertFalse(recheck_ign(record, doc)[0])
        doc = response(record)
        doc["features"][0]["geometry"]["coordinates"][0] += 0.004
        self.assertFalse(recheck_ign(record, doc)[0])

    def test_missing_or_untrusted_source_fails(self):
        record = venue()
        for path in (
            "https://data.geopf.fr.evil.invalid/geocodage/search?q=24%20Rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2",
            "https://data.geopf.fr/geocodage/search?q=24%20Rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=1",
            "http://data.geopf.fr/geocodage/search?q=24%20Rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2",
            "https://data.geopf.fr/geocodage/search?q=Rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2",
            "https://data.geopf.fr/geocodage/search?q=24%20Rue%20Emile%20Decorps%2069100%20Villeurbanne&limit=2#malicious",
        ):
            rec = deepcopy(record)
            rec["geo_source"] = path
            self.assertIsNone(reviewed_search(rec))
            self.assertFalse(recheck_ign(rec, response(record))[0])

    def test_invalid_external_schema_fails(self):
        record = venue()
        for doc in (None, [], {}, {"type": "FeatureCollection", "features": {}},
                    {"type": "FeatureCollection", "features": [{}, {}, {}]}):
            self.assertFalse(recheck_ign(record, doc)[0])

    def test_redacted_report_never_exposes_private_or_venue_names(self):
        records = [venue(city, name) for city, name in TARGETS]
        responses = [response(rec) for rec in records]
        report = redacted_report(records, responses)
        self.assertEqual(report["curated_buildings_checked"], 4)
        self.assertEqual(report["external_exact_housenumber_matches"], 4)
        self.assertEqual(report["public_writes"], 0)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("Studio 24", serialized)
        self.assertNotIn("www.villeurbanne.fr", serialized)
        self.assertNotIn("Villeurbanne", serialized)

    def test_cannot_invent_approval_from_a_location_proof(self):
        record = venue()
        self.assertNotIn("date_start", record)
        result = redacted_report([record], [response(record)])
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["official_event_organizer_and_date_proof_checked"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)

    def test_duplicate_curated_identity_rejected(self):
        rec = venue()
        with self.assertRaisesRegex(ValueError, "duplicate_venue_identity"):
            redacted_report([rec, rec], [response(rec), response(rec)])


if __name__ == "__main__":
    unittest.main()
