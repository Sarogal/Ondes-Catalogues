"""Offline tests: independent postal address corroboration is NOT venue approval."""
from copy import deepcopy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_generic_venue_ign_corroboration import (
    address_candidate, corroborate_osm_records, ign_url, verify_ign,
    MIN_SCORE,
)

GROUP = {"city": "Ville-des-Bois", "venue": "Maison des enfants",
         "key": ["ville des bois", "maison des enfants"], "uids": ["123"]}
OSM = {
    "type": "node", "id": 218, "lat": 44.50, "lon": 2.25,
    "tags": {"name": "Maison des enfants", "addr:city": "Ville-des-Bois",
             "addr:housenumber": "12", "addr:street": "Rue des Chênes",
             "addr:postcode": "12345"},
}


def ban_feature(candidate, score=0.98):
    return {"type": "Feature",
            "properties": {"type": "housenumber", "city": candidate["city"],
                           "postcode": candidate["postcode"],
                           "housenumber": candidate["housenumber"],
                           "label": candidate["address_query"],
                           "score": score},
            "geometry": {"type": "Point",
                         "coordinates": [candidate["lng_osm_hint"],
                                         candidate["lat_osm_hint"]]}}


class GenericIGNCorroborationTests(unittest.TestCase):
    def setUp(self):
        self.candidate = address_candidate(GROUP, OSM)
        self.assertIsNotNone(self.candidate)

    def doc(self):
        return {"type": "FeatureCollection",
                "features": [ban_feature(self.candidate)]}

    def test_exact_osm_address_has_bounded_query(self):
        c = self.candidate
        url = ign_url(c)
        self.assertTrue(url.startswith(
            "https://data.geopf.fr/geocodage/search?q="))
        self.assertIn("limit=2", url)
        self.assertNotIn("openagenda", url)

    def test_missing_street_number_or_postcode_blocks_query(self):
        for name in ("addr:street", "addr:postcode", "addr:housenumber"):
            obj = deepcopy(OSM)
            del obj["tags"][name]
            self.assertIsNone(address_candidate(GROUP, obj))
        obj = deepcopy(OSM)
        obj["tags"]["addr:housenumber"] = "0; DELETE"
        self.assertIsNone(address_candidate(GROUP, obj))

    def test_city_and_venue_mismatch_rejected(self):
        for attr, value in (("name", "École des enfants"),
                            ("addr:city", "Autre-ville")):
            obj = deepcopy(OSM)
            obj["tags"][attr] = value
            self.assertIsNone(address_candidate(GROUP, obj))

    def test_exact_ban_address_does_not_approve_event(self):
        x = verify_ign(self.candidate, self.doc(), (44.50, 2.25))
        self.assertTrue(x["address_correlated"])
        self.assertEqual(x["status"],
                         "ign_exact_address_correlated_official_site_unchecked")
        self.assertFalse(x["gps_verified"])
        self.assertFalse(x["official_venue_verified"])
        self.assertFalse(x["publication_ready"])

    def test_reject_low_score_wrong_street_city_and_postcode(self):
        for patch in ({"score": MIN_SCORE - 0.01},
                      {"city": "Autre-ville"},
                      {"postcode": "54321"},
                      {"housenumber": "13"},
                      {"label": "12 rue des Fleurs 12345 Ville-des-Bois"},
                      {"type": "street"}):
            doc = self.doc()
            doc["features"][0]["properties"].update(patch)
            self.assertFalse(verify_ign(self.candidate, doc)["address_correlated"])

    def test_reject_divergent_location_from_osm_or_organizer(self):
        doc = self.doc()
        doc["features"][0]["geometry"]["coordinates"][0] += 0.009
        self.assertFalse(verify_ign(self.candidate, doc)["address_correlated"])
        self.assertFalse(verify_ign(self.candidate, self.doc(),
                                    (44.51, 2.25))["address_correlated"])

    def test_reject_two_identical_matches(self):
        doc = self.doc()
        doc["features"].append(deepcopy(doc["features"][0]))
        self.assertFalse(verify_ign(self.candidate, doc)["address_correlated"])

    def test_invalid_or_incomplete_source_fails_closed(self):
        for data in ({}, None, {"type": "FeatureCollection",
                               "features": [{}, {}, {}]},
                     {"type": "FeatureCollection", "features": []}):
            self.assertFalse(
                verify_ign(self.candidate, data)["address_correlated"])

    def test_generic_crosscheck_with_exact_osm_feature(self):
        doc = self.doc()
        checked = corroborate_osm_records(
            GROUP, {"elements": [OSM]}, (44.50, 2.25),
            ign_fetch=lambda cand: doc)
        self.assertTrue(checked["address_correlated"])
        self.assertEqual(checked["ign_requests"], 1)
        self.assertFalse(checked["publication_ready"])

    def test_no_address_or_ambiguous_osm_does_not_call_ban(self):
        def forbidden(x):
            raise AssertionError("BAN must not be called")
        osm_no_street = deepcopy(OSM)
        osm_no_street["tags"].pop("addr:street")
        a = corroborate_osm_records(
            GROUP, {"elements": [osm_no_street]}, (44.50, 2.25), forbidden)
        self.assertEqual(a["status"], "osm_street_address_incomplete")
        self.assertEqual(a["ign_requests"], 0)
        b = corroborate_osm_records(
            GROUP, {"elements": [OSM, {**OSM, "id": 219}]},
            (44.50, 2.25), forbidden)
        self.assertEqual(b["status"], "no_unambiguous_osm_address")
        self.assertEqual(b["ign_requests"], 0)

    def test_ban_network_failure_is_not_success(self):
        def bad(x):
            raise ConnectionError("timeout")
        result = corroborate_osm_records(
            GROUP, {"elements": [OSM]}, (44.50, 2.25), bad)
        self.assertEqual(result["status"], "ign_source_unavailable")
        self.assertEqual(result["ign_requests"], 1)
        self.assertFalse(result["address_correlated"])


if __name__ == "__main__":
    unittest.main()
