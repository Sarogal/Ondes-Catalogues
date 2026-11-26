from copy import deepcopy
import unittest
from ptitesondes_open_world_permanent_place_evidence import corroborate_place

CITY, VENUE, ZIP = "Ville", "Ludothèque des enfants", "12345"
URL = "https://venue.example/lieu"
HTML = """<main><h1>Ludothèque des enfants</h1>
<p>Rue des Jeux, 12345 Ville</p>
<p>Ouverte à tous, espace de jeux pour enfants.</p></main>"""
OSM = {"elements": [{"type": "node", "id": 1234, "lat": 45.1, "lon": 3.1,
                     "tags": {"name": VENUE, "amenity": "toy_library",
                              "addr:city": CITY, "addr:postcode": ZIP,
                              "addr:street": "Rue des Jeux",
                              "website": URL}}]}


class OpenWorldPermanentPlaceEvidenceTests(unittest.TestCase):
    def check(self, html=HTML, osm=None, url=URL):
        return corroborate_place(CITY, VENUE, ZIP, url, html,
                                 OSM if osm is None else osm)

    def test_numberless_exact_venue_is_not_rejected(self):
        proof = self.check()
        self.assertIsNotNone(proof)
        self.assertFalse(proof["address_number_present"])
        self.assertFalse(proof["public_eligible"])
        self.assertEqual(proof["osm_object"], "node/1234")

    def test_numbered_venue_requires_exact_number(self):
        osm = deepcopy(OSM)
        osm["elements"][0]["tags"]["addr:housenumber"] = "12"
        self.assertIsNone(self.check(osm=osm))
        self.assertIsNotNone(self.check(HTML.replace("Rue des Jeux", "12 Rue des Jeux"), osm))

    def test_hidden_wrong_or_ambiguous_official_facts_fail(self):
        for html in (
            HTML.replace("<p>Rue", "<p hidden>Rue"),
            HTML.replace("Ouverte à tous", "Sur invitation"),
            HTML.replace("12345 Ville", "12345 Autreville"),
            HTML.replace("</main>", "<p>Fermeture définitive</p></main>"),
            HTML.replace("</main>", "<h1>Autre lieu</h1></main>"),
            HTML.replace("Ludothèque des enfants", "Autre lieu"),
        ):
            self.assertIsNone(self.check(html), html)

    def test_independent_mapping_is_required(self):
        for key, value in (("addr:city", "Autreville"), ("addr:postcode", "54321"),
                           ("website", "https://other.example/lieu"),
                           ("access", "private"), ("amenity", "parking")):
            osm = deepcopy(OSM)
            osm["elements"][0]["tags"][key] = value
            self.assertIsNone(self.check(osm=osm), key)
        osm = deepcopy(OSM)
        obj = deepcopy(osm["elements"][0])
        obj["id"] = 1235
        osm["elements"].append(obj)
        self.assertIsNone(self.check(osm=osm))
        self.assertIsNone(self.check(url="https://other.example/lieu"))

    def test_unresolved_geometry_is_not_a_point(self):
        for kind in ("way", "relation"):
            osm = deepcopy(OSM)
            osm["elements"][0]["type"] = kind
            self.assertIsNone(self.check(osm=osm))


if __name__ == "__main__":
    unittest.main()
