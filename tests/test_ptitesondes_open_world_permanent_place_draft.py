from copy import deepcopy
from datetime import date
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import CITY, VENUE, ZIP, URL, HTML, OSM
from ptitesondes_open_world_permanent_place_draft import build_draft, administrative_identity

DAY = date(2026, 11, 26)
ADMIN = [{"nom": CITY, "code": "12345", "codesPostaux": [ZIP],
          "codeDepartement": "12", "departement": {"code": "12", "nom": "Département test"},
          "codeRegion": "76", "region": {"code": "76", "nom": "Région test"}}]


class OpenWorldPlaceDraftTests(unittest.TestCase):
    def check(self, html=HTML, osm=OSM, admin=ADMIN):
        return build_draft(CITY, VENUE, ZIP, URL, html, osm, admin, DAY)

    def test_complete_record_unknown_age_and_price_not_fabricated(self):
        d = self.check()
        self.assertIsNotNone(d)
        self.assertEqual(d["id"], "osm-node-1234")
        self.assertEqual(d["address"], "Rue des Jeux, 12345 Ville")
        self.assertEqual(d["region"], "Région test")
        self.assertIsNone(d["age_min"])
        self.assertIsNone(d["age_max"])
        self.assertEqual(d["activities"], ["jeux pour enfants"])
        self.assertEqual(d["admission"], "ouvert à tous — tarif à vérifier")

    def test_unknown_or_ambiguous_administration(self):
        for admin in ([], ADMIN + ADMIN, [dict(ADMIN[0], nom="Other")],
                      [dict(ADMIN[0], codesPostaux=["54321"])],
                      [dict(ADMIN[0], region=None)]):
            self.assertIsNone(self.check(admin=admin))

    def test_activities_must_be_explicit_not_heading_or_navigation(self):
        self.assertIsNone(self.check(HTML.replace("espace de jeux pour enfants", "informations")))
        self.assertIsNone(self.check(HTML.replace("<p>Ouverte", "<nav><p>Ouverte")
                                     .replace("enfants.</p>", "enfants.</p></nav>")))

    def test_explicit_address_and_access_must_be_in_main_content(self):
        self.assertIsNone(self.check(HTML.replace("<p>Rue", "<footer><p>Rue")
                                     .replace("Ville</p>", "Ville</p></footer>")))
        self.assertIsNone(self.check(HTML.replace("Ouverte à tous", "Pas ouverte à tous")))
        self.assertIsNone(self.check(HTML.replace("</main>", "<p>Fermeture temporaire</p></main>")))

    def test_explicit_free_access_and_numbered_address(self):
        osm = deepcopy(OSM)
        osm["elements"][0]["tags"]["addr:housenumber"] = "12"
        html = HTML.replace("Rue des Jeux", "12 Rue des Jeux").replace(
            "Ouverte à tous", "Accès libre et gratuit")
        result = self.check(html, osm)
        self.assertEqual(result["admission"], "accès libre et gratuit")
        self.assertEqual(result["address"], "12 Rue des Jeux, 12345 Ville")


if __name__ == "__main__":
    unittest.main()
