"""Adversarial offline venue proof for squares, streets and places without numbers."""
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_unnumbered_official_geo_proof import (
    mint_private_unnumbered_location_proof,
)
from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, location_from_proof,
)
from ptitesondes_generic_venue_osm_preflight import inspect_group

DAY = date(2026, 11, 20)
CITY = "Ville-les-Bois"
VENUE = "Place du village"
GROUP = {
    "city": CITY, "venue": VENUE, "key": ["ville les bois", "place du village"],
    "uids": ["721"], "lead_count": 1, "unique_candidate_sessions": 1,
}
POINT = (44.5, 2.25)
URL = "https://www.ville-les-bois.fr/lieux/place-du-village"


def directory():
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + CITY, "categorie": "SL",
        "version_type": "Publiable", "statut_de_diffusion": "true",
        "copyright": "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": json.dumps([{"type_service_local": "mairie",
                              "code_insee_commune": ["12345"]}]),
        "adresse": json.dumps([{"nom_commune": CITY, "pays": "France"}]),
        "site_internet": json.dumps([{
            "libelle": "", "valeur": "https://www.ville-les-bois.fr/",
        }]),
    }]}


def html(venue=VENUE, point=POINT, *, city=CITY, country="FR",
         include_geo=True):
    node = {"@type": "Place", "name": venue,
            "address": {"@type": "PostalAddress",
                        "addressLocality": city,
                        "addressCountry": country}}
    if include_geo:
        node["geo"] = {"@type": "GeoCoordinates",
                       "latitude": point[0], "longitude": point[1]}
    return ("<html><script type='application/ld+json'>"
            + json.dumps(node, ensure_ascii=False)
            + "</script></html>")


def osm(venue=VENUE, point=POINT, city=None, *, duplicate=False):
    tags = {"name": venue, "highway": "pedestrian"}
    if city is not None:
        tags["addr:city"] = city
    elements = [{"type": "way", "id": 42,
                 "center": {"lat": point[0], "lon": point[1]},
                 "tags": tags}]
    if duplicate:
        elements.append({**elements[0], "id": 43})
    return {"elements": elements}


def mint(**overrides):
    inputs = dict(
        group=GROUP, directory=directory(), official_url=URL,
        official_html=html(), osm_response=osm(), source_center=POINT,
        checked_on=DAY,
    )
    inputs.update(overrides)
    return mint_private_unnumbered_location_proof(**inputs)


class UnnumberedOfficialGeoTests(unittest.TestCase):
    def test_public_square_without_number_yields_private_location_only(self):
        proof = mint()
        self.assertIsInstance(proof, VenueLocationProof)
        self.assertEqual(proof.method, "dila_official_geo_plus_named_osm")
        loc = location_from_proof(proof, CITY, VENUE, DAY, POINT)
        self.assertEqual((loc["lat"], loc["lng"]), POINT)
        self.assertIn("named OSM", loc["geo_source"])
        self.assertIsNone(location_from_proof(
            proof, CITY, VENUE, DAY + timedelta(days=31)))
        with self.assertRaises(AttributeError):
            proof.lat = 0

    def test_not_restricted_to_curated_outdoor_types_or_numbered_address(self):
        group = {**GROUP, "venue": "Rue du futur",
                 "key": ["ville les bois", "rue du futur"]}
        proof = mint(group=group, official_html=html("Rue du futur"),
                     osm_response=osm("Rue du futur"))
        self.assertIsInstance(proof, VenueLocationProof)
        self.assertIsNotNone(location_from_proof(
            proof, CITY, "Rue du futur", DAY, POINT))

    def test_osm_city_tag_is_optional_if_official_geo_proves_city(self):
        self.assertIsNotNone(mint(osm_response=osm(city=None)))

    def test_no_official_coords_means_hint_only_not_location_proof(self):
        self.assertIsNone(mint(official_html=html(include_geo=False)))

    def test_disagreement_of_sources_is_not_publishable(self):
        for params in (
            {"source_center": (44.51, 2.25)},
            {"official_html": html(point=(44.51, 2.25))},
            {"osm_response": osm(point=(44.51, 2.25))},
            {"osm_response": osm(duplicate=True)},
            {"osm_response": osm(venue="Autre parc")},
            {"osm_response": osm(city="Autre ville")},
            {"official_html": html(venue="Autre place")},
            {"official_html": html(city="Autre commune")},
            {"official_html": html(country="DE")},
            {"official_url": "https://wrong.example/location"},
            {"official_url": "https://www.ville-les-bois.fr/"},
            {"directory": {"results": []}},
            {"checked_on": "2026-11-20"},
        ):
            with self.subTest(case=str(params)[:60]):
                self.assertIsNone(mint(**params))

    def test_opt_in_preflight_counts_proven_place_without_publishing(self):
        row = {"uid": "721", "location_city": CITY, "location_name": VENUE,
               "location_coordinates": {"lat": POINT[0], "lon": POINT[1]}}
        result = inspect_group(
            GROUP, record_fetch=lambda uid: row,
            osm_fetch=lambda _: osm(), ign_fetch=lambda _: {},
            official_page_get=lambda _: (URL, html()),
            dila_directory_get=lambda _: directory(),
            shared_proof_day=DAY,
        )
        self.assertTrue(result["shared_location_proof_private_review"])
        self.assertTrue(result["unnumbered_named_venue_hint"][
            "official_name_correlated"])
        self.assertNotIn("additions", result)
        self.assertNotIn("events", result)

    def test_without_explicit_shared_proof_day_remains_hint_only(self):
        row = {"uid": "721", "location_city": CITY, "location_name": VENUE,
               "location_coordinates": {"lat": POINT[0], "lon": POINT[1]}}
        result = inspect_group(
            GROUP, record_fetch=lambda uid: row,
            osm_fetch=lambda _: osm(), ign_fetch=lambda _: {},
            official_page_get=lambda _: (URL, html()),
            dila_directory_get=lambda _: directory(),
        )
        self.assertNotIn("shared_location_proof_private_review", result)
        self.assertTrue(result["unnumbered_named_venue_hint"][
            "official_name_correlated"])


if __name__ == "__main__":
    unittest.main()
