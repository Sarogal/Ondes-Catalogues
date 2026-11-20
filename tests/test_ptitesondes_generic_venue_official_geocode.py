"""Offline tests for venue official-address -> BAN geocode without OSM."""
import json
import sys
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_generic_venue_official_geocode import (
    extract_official_address, confirm_official_address_ban,
)
from ptitesondes_generic_venue_osm_preflight import (
    inspect_group, audit, groups_for_review,
)

DAY = date(2026, 11, 20)
GROUP = {"city": "Ville-des-Bois", "venue": "Maison des enfants",
         "key": ["ville des bois", "maison des enfants"], "uids": ["721"],
         "lead_count": 1}
URL = "https://www.ville-des-bois.fr/lieux/maison-des-enfants"
SOURCE = (44.5, 2.25)


def directory():
    return {"total_count": 1, "results": [{
        "nom": "Mairie - Ville-des-Bois", "categorie": "SL",
        "statut_de_diffusion": "true", "version_type": "Publiable",
        "copyright":
            "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": '[{"type_service_local":"mairie","code_insee_commune":["12345"]}]',
        "adresse": '[{"nom_commune":"Ville-des-Bois","pays":"France"}]',
        "site_internet":
            '[{"libelle":"","valeur":"https://www.ville-des-bois.fr/"}]',
    }]}


def jsonld_html(street="12 Rue des Chênes", code="12345",
                city="Ville-des-Bois", geo=None):
    node = {"@type": "Place", "name": "Maison des enfants",
            "address": {"@type": "PostalAddress",
                        "streetAddress": street, "postalCode": code,
                        "addressLocality": city}}
    if geo is not None:
        node["geo"] = {"latitude": geo[0], "longitude": geo[1]}
    return ("<html><script type='application/ld+json'>"
            + json.dumps(node, ensure_ascii=False) + "</script>"
            "<h1>Maison des enfants</h1></html>")


def visible_html(address="12 Rue des Chênes, 12345 Ville-des-Bois"):
    return ("<html><main><h1>Maison des enfants</h1>"
            "<address>" + address + "</address></main></html>")


def ban(score=0.99):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"type": "housenumber", "score": score,
                       "city": "Ville-des-Bois", "postcode": "12345",
                       "housenumber": "12",
                       "label": "12 Rue des Chênes 12345 Ville-des-Bois"},
        "geometry": {"type": "Point", "coordinates": [2.25, 44.5]},
    }]}


def source_record(uid):
    return {"uid": uid, "location_city": "Ville-des-Bois",
            "location_name": "Maison des enfants",
            "location_coordinates": {"lat": 44.5, "lon": 2.25}}


def lead():
    return {"city": GROUP["city"], "venue": GROUP["venue"],
            "title": "Atelier enfant", "collector": "openagenda-v2",
            "external_id": "721",
            "source_url": "https://openagenda.com/agenda-demo/events/721_atelier",
            "date_start": "2026-12-12", "date_end": "2026-12-12"}


class OfficialFirstGeocodeTests(unittest.TestCase):
    def proof(self, html=None, query=None, url=URL, group=GROUP,
              source=SOURCE, directory_data=None):
        return confirm_official_address_ban(
            group, source,
            directory() if directory_data is None else directory_data,
            url, jsonld_html() if html is None else html,
            (lambda c: ban()) if query is None else query)

    def test_official_schema_address_plus_ban_independent_without_osm(self):
        x = self.proof()
        self.assertTrue(x["independent_geo_correlated"])
        self.assertEqual(x["status"],
                         "official_address_ban_source_private_review")
        self.assertFalse(x["official_venue_verified_for_publisher"])
        self.assertFalse(x["gps_verified_for_publisher"])
        self.assertFalse(x["event_sessions_verified"])
        self.assertFalse(x["publication_ready"])
        self.assertEqual(x["public_writes"], 0)

    def test_visible_h1_and_postal_address_are_allowed_no_schema(self):
        candidate = extract_official_address(GROUP, visible_html())
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["postcode"], "12345")
        self.assertTrue(self.proof(html=visible_html())[
            "independent_geo_correlated"])

    def test_conflicting_city_street_house_and_postcode_fail(self):
        for p in (
            {"street": "13 Rue des Chênes"}, {"code": "54321"},
            {"city": "Other City"},
        ):
            with self.subTest(changed=p):
                self.assertFalse(self.proof(html=jsonld_html(**p))[
                    "independent_geo_correlated"])

    def test_bad_visible_address_and_duplicate_hidden_data_fail(self):
        for page in (
            visible_html("13 Rue des Chênes, 12345 Ville-des-Bois"),
            "<html><h1>Autre lieu</h1><address>"
            "12 Rue des Chênes, 12345 Ville-des-Bois</address></html>",
            "<html><h1>Maison des enfants</h1>"
            "<footer><address>12 Rue des Chênes, 12345 Ville-des-Bois"
            "</address></footer></html>",
        ):
            with self.subTest(page=page[:45]):
                r = self.proof(html=page)
                self.assertFalse(r["independent_geo_correlated"])

    def test_ban_low_score_ambiguous_or_divergent_coordinates_fail(self):
        low = self.proof(query=lambda c: ban(score=0.4))
        self.assertFalse(low["independent_geo_correlated"])
        ambiguous = ban()
        ambiguous["features"].append(deepcopy(ambiguous["features"][0]))
        self.assertFalse(self.proof(query=lambda c: ambiguous)[
            "independent_geo_correlated"])
        shifted = ban()
        shifted["features"][0]["geometry"]["coordinates"][0] += 0.05
        self.assertFalse(self.proof(query=lambda c: shifted)[
            "independent_geo_correlated"])

    def test_official_schema_geo_conflict_blocks_even_if_ban_matches(self):
        self.assertFalse(self.proof(
            html=jsonld_html(geo=(44.55, 2.25)))["independent_geo_correlated"])

    def test_unapproved_host_and_provider_unavailable_fail_closed(self):
        self.assertFalse(self.proof(
            url="https://ville-des-bois.fr.evil.test/lieu")[
                "independent_geo_correlated"])
        self.assertEqual(self.proof(query=Mock(
            side_effect=TimeoutError("provider down")))["status"],
            "ban_source_unavailable")
        self.assertFalse(self.proof(directory_data={
            "total_count": 0, "results": []})["independent_geo_correlated"])

    def test_inspect_group_official_first_skips_osm_provider(self):
        blocked = Mock(side_effect=AssertionError("OSM should be skipped"))
        result = inspect_group(
            GROUP, record_fetch=source_record, osm_fetch=blocked,
            ign_fetch=lambda c: ban(), official_page_get=lambda g: (
                URL, jsonld_html()),
            dila_directory_get=lambda city: directory(),
            official_geocode=True,
        )
        blocked.assert_not_called()
        self.assertEqual(result["status"], "official_address_ban_private_review")
        self.assertTrue(result["official_geocode"]["independent_geo_correlated"])
        self.assertEqual(result["osm_candidates_unverified"], [])

    def test_audit_counts_potential_leads_not_publisher_approval(self):
        r = audit(
            [lead()], DAY,
            record_fetch=source_record,
            osm_fetch=Mock(side_effect=AssertionError("No OSM")),
            ign_fetch=lambda c: ban(),
            official_page_get=lambda g: (URL, visible_html()),
            dila_directory_get=lambda city: directory(),
            official_geocode=True, live=True,
        )
        self.assertEqual(r["independent_official_ban_address_matches"], 1)
        self.assertEqual(r["leads_with_official_ban_geo_private_review"], 1)
        self.assertEqual(r["verified_venue_leads"], 0)
        self.assertFalse(r["official_venue_verified"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(r["public_writes"], 0)

    def test_official_first_disabled_by_default_never_reads_private_web(self):
        unavailable = Mock(side_effect=AssertionError("official proof disabled"))
        result = inspect_group(
            GROUP, record_fetch=source_record,
            osm_fetch=lambda c: {"elements": []},
            ign_fetch=lambda c: ban(),
            official_page_get=unavailable,
            dila_directory_get=lambda city: directory(),
            official_geocode=False,
        )
        unavailable.assert_not_called()
        self.assertEqual(result["status"], "no_exact_osm_venue_found")


if __name__ == "__main__":
    unittest.main()
