"""No-network adversarial tests for municipal event-page named venue GPS."""
from copy import deepcopy
from datetime import date
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_unnumbered_official_geo_proof import (
    CITY, POINT, directory,
)
from ptitesondes_municipal_event_venue_ban import (
    mint_municipal_event_location_proof,
)
from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, location_from_proof,
)

VENUE = "L'Atelier des rêves"
GROUP = {"city": CITY, "venue": VENUE}
URL = "https://www.ville-les-bois.fr/evenement/atelier-enfants"
DAY = date(2026, 11, 21)


def municipal(title=VENUE, street="1 esplanade Charles-de-Gaulle",
              *, prefix="", suffix=""):
    return ("<html><main><article><h1>Concert pour enfants</h1>"
            "<p>Lieu : " + title + "</p>"
            "<h2>Horaires</h2><p>11h et 16h</p>"
            "<h2>Adresse</h2><div>" + street + "</div>"
            "<a href='https://maps.example/'>Itinéraire</a>"
            + prefix + "</article>" + suffix + "</main></html>")


def ban(number="1", street="Esplanade Charles de Gaulle",
        city=CITY, score=0.99, coords=POINT, typ="housenumber"):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"type": typ, "housenumber": number,
                        "street": street, "city": city,
                        "postcode": "12345", "score": score},
         "geometry": {"type": "Point",
                      "coordinates": [coords[1], coords[0]]}},
    ]}


def mint(page=None, response=None, source=POINT, group=GROUP, url=URL,
         directory_data=None):
    return mint_municipal_event_location_proof(
        group, directory() if directory_data is None else directory_data,
        url, municipal() if page is None else page,
        lambda q: ban() if response is None else response, DAY, source)


class MunicipalEventVenueBANTests(unittest.TestCase):
    def test_explicit_municipal_event_location_with_no_postcode_has_gps(self):
        proof = mint()
        self.assertIsInstance(proof, VenueLocationProof)
        self.assertEqual(proof.method,
                         "dila_municipal_event_address_plus_ban")
        place = location_from_proof(
            proof, CITY, VENUE, DAY, source_point=POINT)
        self.assertEqual((place["lat"], place["lng"]), POINT)
        self.assertIn("Municipal event venue", place["geo_source"])

    def test_city_venue_and_ban_cannot_be_inferred_from_untrusted_index(self):
        for change in (
            {"page": municipal(title="Autre lieu")},
            {"page": municipal(street="Place sans numéro")},
            {"page": municipal(street="1 autre rue")},
            {"page": municipal(suffix=(
                "<article><h1>Autre concert</h1><p>" + VENUE +
                "</p><h2>Adresse</h2><p>2 rue des Roses</p></article>"))},
            {"url": "https://fake-municipality.example/events"},
            {"url": "https://www.ville-les-bois.fr/"},
            {"directory_data": {"results": []}},
            {"response": ban(street="Rue des Roses")},
            {"response": ban(city="Autre ville")},
            {"response": ban(number="2")},
            {"response": ban(score=0.70)},
            {"response": ban(typ="street")},
            {"response": ban(coords=(44.55, 2.25))},
            {"source": (44.55, 2.25)},
        ):
            with self.subTest(change=change):
                self.assertIsNone(mint(**change))

    def test_duplicate_features_missing_coordinates_and_secret_html_fail(self):
        repeated = ban()
        repeated["features"].append(deepcopy(repeated["features"][0]))
        for doc in (repeated, {"type": "FeatureCollection", "features": []},
                    {"type": "FeatureCollection", "features": [{}, {}, {}]},
                    {}):
            self.assertIsNone(mint(response=doc))
        for doc in (
            "<html><main><footer>" + municipal() + "</footer></main></html>",
            "<html><main><script>" + municipal() + "</script></main></html>",
            municipal(title="Autre lieu", suffix=(
                "<footer><p>" + VENUE + "</p></footer>")),
        ):
            self.assertIsNone(mint(page=doc))

    def test_municipal_event_page_cannot_approve_event_session(self):
        proof = mint()
        self.assertFalse(hasattr(proof, "session_verified"))
        self.assertFalse(hasattr(proof, "publication_ready"))
        self.assertIsNone(location_from_proof(
            proof, CITY, "Un autre lieu", DAY, POINT))


if __name__ == "__main__":
    unittest.main()
