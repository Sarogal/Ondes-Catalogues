from copy import deepcopy
import unittest

from test_ptitesondes_dila_municipal_domains import CITY, PAGE, mairie, payload
from ptitesondes_open_world_permanent_place_ban import (
    official_facts, corroborate_official_ban,
)

VENUE = "Ludothèque des enfants"
HTML = f"<main><h1>{VENUE}</h1><p>12 Rue des Jeux, 12345 {CITY}</p><p>Ouverte à tous, espace de jeux pour enfants.</p></main>"
DIR = payload(mairie())
BAN = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "properties": {"type": "housenumber", "score": .99, "citycode": "12345",
                   "postcode": "12345", "city": CITY, "housenumber": "12",
                   "street": "Rue des Jeux", "label": f"12 Rue des Jeux 12345 {CITY}"},
    "geometry": {"type": "Point", "coordinates": [3.1, 45.1]}}]}
ADMIN = [{"nom": CITY, "code": "12345", "codesPostaux": ["12345"],
          "codeDepartement": "12", "departement": {"code": "12", "nom": "Test"},
          "codeRegion": "76", "region": {"code": "76", "nom": "Test"}}]


class OfficialPlaceBANTests(unittest.TestCase):
    def check(self, html=HTML, directory=DIR, ban=BAN, admin=ADMIN, url=PAGE):
        return corroborate_official_ban(CITY, VENUE, url, html, directory,
                                      lambda _: ban, lambda *_: admin)

    def test_independent_precise_address_without_osm_or_event_uid(self):
        d = self.check()
        self.assertIsNotNone(d)
        self.assertEqual((d["lat"], d["lng"]), (45.1, 3.1))
        self.assertEqual(d["category"], "ludotheque")
        self.assertFalse(d["public_eligible"])
        self.assertFalse(d["publication_ready"])
        self.assertEqual(d["public_writes"], 0)

    def test_unofficial_host_or_wrong_city_rejected_before_geocoding(self):
        for url, directory in (("https://other.example/lieu", DIR),
                               (PAGE, payload(mairie(city="Autre ville")))):
            self.assertIsNone(corroborate_official_ban(
                CITY, VENUE, url, HTML, directory,
                lambda _: self.fail("unexpected BAN fetch"),
                lambda *_: self.fail("unexpected admin fetch")))

    def test_hidden_or_conflicting_or_numberless_address_does_not_pass_ban(self):
        for html in (
            HTML.replace("<p>12", "<p hidden>12"),
            HTML.replace("12 Rue", "Rue"),
            HTML.replace("</main>", f"<p>14 Rue des Jeux, 12345 {CITY}</p></main>"),
            HTML.replace("Ouverte à tous", "Pas ouverte à tous"),
            HTML.replace("espace de jeux pour enfants", "informations"),
            HTML.replace("</main>", "<p>Fermeture définitive</p></main>"),
            HTML.replace(f"<h1>{VENUE}</h1>", "").replace("<main>", f"<h1>{VENUE}</h1><main>"),
        ):
            self.assertIsNone(official_facts(CITY, VENUE, PAGE, html, DIR), html)

    def test_wrong_ban_citycode_postcode_score_or_centroid(self):
        for key, value in (("citycode", "99999"), ("postcode", "99999"),
                           ("score", .80), ("type", "street"), ("housenumber", "14")):
            ban = deepcopy(BAN)
            ban["features"][0]["properties"][key] = value
            self.assertIsNone(self.check(ban=ban))
        ban = deepcopy(BAN)
        ban["features"] *= 2
        self.assertIsNone(self.check(ban=ban))

    def test_administrative_identity_must_agree(self):
        self.assertIsNone(self.check(admin=[dict(ADMIN[0], code="99999")]))
        self.assertIsNone(self.check(admin=[]))

    def test_ban_unavailable_is_not_publication_permission(self):
        def down(_):
            raise OSError("provider unavailable")
        self.assertIsNone(corroborate_official_ban(CITY, VENUE, PAGE, HTML, DIR,
                                                  down, lambda *_: ADMIN))


if __name__ == "__main__":
    unittest.main()
