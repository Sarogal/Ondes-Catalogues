"""Offline safety tests for redundant read-only OSM transport.

Fail over ONLY after a network failure. A successful contradictory OSM
response is final and can never be overwritten by another provider.
"""
import json
import unittest

from automation.concerts import osm_read_only_fallback as readonly
from automation.concerts import independent_named_site_geo as geo
from automation.concerts import event_site_pair_recheck as pairing
from scripts import concert_dynamic_existing_venue as existing
import test_concerts_dynamic_existing_venue as fixture


class SecondaryReadOnlyOSMTests(unittest.TestCase):
    def test_only_two_static_providers_and_numeric_identifiers(self):
        first = readonly.element("node", "380889428")
        second = readonly.element("node", "380889428", provider=1)
        self.assertTrue(first.startswith(
            "https://overpass.private.coffee/api/interpreter?"))
        self.assertTrue(second.startswith(
            "https://overpass-api.de/api/interpreter?"))
        self.assertEqual(first.split("?", 1)[1], second.split("?", 1)[1])
        for provider in (-1, 2, True, "https://evil.invalid"):
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    readonly.element("node", "380889428", provider=provider)
                with self.assertRaises(ValueError):
                    readonly.nearby(47.394, 0.687, 47.396, 0.689,
                                    provider=provider)
        with self.assertRaises(ValueError):
            readonly.element("node", "12);out body;")

    def test_osm_second_provider_can_restore_exact_domain_attribution(self):
        venue = next(v for v in fixture.BASE["venues"]
                     if v["id"] == fixture.VENUE_ID)
        visited = []
        def fetch(url, cache):
            visited.append(url)
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("editing API unreachable")
            if url.startswith("https://www.openstreetmap.org/api/"):
                raise TimeoutError("editing API unavailable")
            if url.startswith("https://overpass.private.coffee/"):
                raise TimeoutError("first read-only provider busy")
            if url.startswith("https://overpass-api.de/"):
                return fixture.osm()
            raise AssertionError("Unsupported host")
        self.assertEqual(
            existing.osm_identity(venue, fixture.EVENT, fetch, {}),
            venue["geoSource"])
        self.assertTrue(any("overpass.private.coffee" in x for x in visited))
        self.assertTrue(any("overpass-api.de" in x for x in visited))

        def wrong(url, cache):
            if url.startswith("https://overpass-api.de/"):
                return fixture.osm(website="https://forged.invalid")
            return fetch(url, cache)
        with self.assertRaises(ValueError):
            existing.osm_identity(venue, fixture.EVENT, wrong, {})

    def test_exact_government_address_osm_map_can_use_second_provider(self):
        site = {
            "name": "Salle Libre", "city": "Tours", "postalCode": "37000",
            "address": "1 rue Exemple", "region": "Centre-Val de Loire",
        }
        gov = json.dumps({"features": [{
            "geometry": {"type": "Point", "coordinates": [0.688, 47.395]},
            "properties": {
                "postcode": "37000", "city": "Tours",
                "street": "rue Exemple", "housenumber": "1",
                "type": "housenumber", "score": 0.82,
            },
        }]})
        xml = ('<osm version="0.6"><node id="912345678" '
               'lat="47.395" lon="0.688">'
               '<tag k="name" v="Salle Libre"/>'
               '<tag k="addr:city" v="Tours"/>'
               '<tag k="addr:postcode" v="37000"/>'
               '<tag k="addr:street" v="rue Exemple"/>'
               '<tag k="addr:housenumber" v="1"/>'
               '</node></osm>')
        visited = []
        def fetch(url, cap):
            visited.append(url)
            if url.startswith("https://data.geopf.fr/"):
                return gov, url
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("editing API blocked")
            if url.startswith("https://overpass.private.coffee/"):
                raise TimeoutError("provider timed out")
            if url.startswith("https://overpass-api.de/"):
                return xml, url
            raise AssertionError("Unexpected OSM proof route")
        point, lat, lon, precision = geo.verify(site, fetch)
        self.assertEqual(point, "https://www.openstreetmap.org/node/912345678")
        self.assertEqual(precision, "named-site-point")
        self.assertTrue(any("overpass-api.de" in u for u in visited))
        def contradiction(url, cap):
            if url.startswith("https://overpass.private.coffee/"):
                return xml.replace("Salle Libre", "Different Venue"), url
            return fetch(url, cap)
        with self.assertRaises(ValueError):
            geo.verify(site, contradiction)

    def test_new_site_osm_node_exact_json_identity_from_second_provider(self):
        expected = {"name": "Salle Libre", "city": "Tours",
                    "postalCode": "37000"}
        obj = json.dumps({"elements": [{
            "id": 912345678, "type": "node", "lat": 47.395,
            "lon": 0.688, "tags": {
                "name": "Salle Libre", "addr:city": "Tours",
                "addr:postcode": "37000", "addr:country": "FR",
            },
        }]})
        def fetch(url, cap):
            if url.startswith("https://overpass-api.de/"):
                return obj, url
            raise TimeoutError("primary OSM transport unavailable")
        self.assertEqual(
            pairing._read_osm_node(
                "https://www.openstreetmap.org/node/912345678",
                expected, fetch),
            (47.395, 0.688))
        def forged(url, cap):
            if url.startswith("https://overpass-api.de/"):
                return obj.replace("Salle Libre", "Impostor Venue"), url
            return fetch(url, cap)
        with self.assertRaises(ValueError):
            pairing._read_osm_node(
                "https://www.openstreetmap.org/node/912345678",
                expected, forged)


if __name__ == "__main__":
    unittest.main()
