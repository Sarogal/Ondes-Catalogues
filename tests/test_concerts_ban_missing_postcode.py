"""Offline tests for independent BAN completion of missing postal codes."""
import copy
import json
import unittest

from automation.concerts import existing_venue_geo_evidence as evidence

geo = evidence.geo
SITE = {"name": "Example Room", "address": "5 place Notre Dame",
        "city": "Tourcoing", "department": "59", "region": "Hauts-de-France",
        "postalCode": None}


def feature(**changes):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.16, 50.72]},
            "properties": {"postcode": "59200", "city": "Tourcoing",
                           "street": "Place Notre Dame", "type": "housenumber",
                           "housenumber": "5", "score": 0.95,
                           "context": "59, Nord, Hauts-de-France", **changes}}


def response(rows):
    return lambda url, cap: (json.dumps({"features": rows}), url)


class MissingPostalCodeTests(unittest.TestCase):
    def test_unique_exact_postcode_is_research_only_and_does_not_mutate_site(self):
        before = copy.deepcopy(SITE)
        self.assertEqual(geo.independently_resolve_postcode(SITE, response([feature()])), "59200")
        self.assertEqual(SITE, before)

    def test_rejects_city_street_department_region_house_and_score_conflicts(self):
        for changes in ({"city": "Lille"}, {"street": "Rue Notre Dame"},
                        {"context": "62, Pas-de-Calais, Hauts-de-France"},
                        {"context": "59, Nord, Grand Est"},
                        {"housenumber": "15"}, {"type": "street"},
                        {"score": 0.77}, {"postcode": "unknown"}, {"context": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                geo.independently_resolve_postcode(SITE, response([feature(**changes)]))

    def test_no_arbitrary_tie_break_or_overwriting_explicit_postcode(self):
        for rows in ([feature(), feature(postcode="59100")], [feature(), feature()], []):
            with self.assertRaises(ValueError):
                geo.independently_resolve_postcode(SITE, response(rows))
        with self.assertRaises(ValueError):
            geo.independently_resolve_postcode(dict(SITE, postalCode="59100"), response([feature()]))

    def test_unnumbered_exact_street_stays_eligible(self):
        row = feature(type="street", housenumber=None)
        self.assertEqual(geo.independently_resolve_postcode(
            dict(SITE, address="place Notre Dame"), response([row])), "59200")
