"""Offline adversarial evidence tests for visible official named venue address."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_generic_venue_visible_address import (
    visible_venue_identity_matches,
)
from ptitesondes_generic_venue_official_proof import official_venue_page_proof

GROUP = {"city": "Ville-des-Bois", "venue": "Maison des enfants"}
CANDIDATE = {
    "city": "Ville-des-Bois", "venue": "Maison des enfants",
    "postcode": "12345", "housenumber": "12",
    "street": "Rue des Chênes", "lat_osm_hint": 44.5,
    "lng_osm_hint": 2.25,
}
BAN = {"address_correlated": True, "gps_verified": False,
       "publication_ready": False}
URL = "https://ville-des-bois.fr/lieux/maison-des-enfants"
HOSTS = frozenset({"ville-des-bois.fr"})

def page(heading="Maison des enfants",
         address="12 Rue des Chênes, 12345 Ville-des-Bois",
         extra=""):
    return ("<html><body><main><h1>" + heading + "</h1>"
            "<address>" + address + "</address>" + extra
            + "</main></body></html>")


class VisibleVenueAddressTests(unittest.TestCase):
    def test_exact_visible_h1_and_address_independently_attested(self):
        self.assertTrue(visible_venue_identity_matches(
            GROUP, CANDIDATE, page()))
        r = official_venue_page_proof(
            GROUP, CANDIDATE, BAN, URL, page(), HOSTS)
        self.assertTrue(r["official_identity_verified"])
        self.assertTrue(r["location_evidence_complete_for_private_review"])
        self.assertEqual(r["status"],
                         "official_visible_name_address_private_review")
        self.assertFalse(r["event_sessions_verified"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(r["public_writes"], 0)

    def test_nested_visible_markups_in_heading_and_address(self):
        markup = page(heading="Maison <span>des enfants</span>",
                      address="12 Rue <strong>des Chênes</strong>, "
                              "<span>12345 Ville-des-Bois</span>")
        self.assertTrue(visible_venue_identity_matches(
            GROUP, CANDIDATE, markup))

    def test_wrong_venue_address_city_postcode_house_rejected(self):
        for kw in (
            {"heading": "Maison du théâtre"},
            {"heading": "Maison des enfants de la ville"},
            {"address": "13 Rue des Chênes, 12345 Ville-des-Bois"},
            {"address": "12 Rue des Chênes, 54321 Ville-des-Bois"},
            {"address": "12 Rue des Chênes, 12345 Autreville"},
            {"address": "Rue des Chênes, 12345 Ville-des-Bois"},
        ):
            with self.subTest(kw=kw):
                self.assertFalse(visible_venue_identity_matches(
                    GROUP, CANDIDATE, page(**kw)))

    def test_untrusted_host_never_grants_evidence(self):
        for url, approved in (
            ("https://ville-des-bois.fr.evil.test/lieu", HOSTS),
            ("https://openagenda.com/agenda/events/page", HOSTS),
            (URL, frozenset()),
        ):
            self.assertFalse(official_venue_page_proof(
                GROUP, CANDIDATE, BAN, url, page(), approved
            )["official_identity_verified"])

    def test_missing_ban_evidence_never_grants_evidence(self):
        bad = {**BAN, "address_correlated": False}
        self.assertFalse(official_venue_page_proof(
            GROUP, CANDIDATE, bad, URL, page(), HOSTS
        )["official_identity_verified"])

    def test_hidden_headings_and_footer_addresses_ignored(self):
        for html in (
            "<html><main><h1 hidden>Maison des enfants</h1>"
            "<address>12 Rue des Chênes, 12345 Ville-des-Bois</address></main></html>",
            "<html><h1>Maison des enfants</h1>"
            "<footer><address>12 Rue des Chênes, 12345 Ville-des-Bois</address>"
            "</footer></html>",
            "<html><h1>Maison des enfants</h1><address style='display:none'>"
            "12 Rue des Chênes, 12345 Ville-des-Bois</address></html>",
        ):
            with self.subTest(markup=html):
                self.assertFalse(visible_venue_identity_matches(
                    GROUP, CANDIDATE, html))

    def test_multiple_headings_or_addresses_are_ambiguous(self):
        for extra in ("<h1>Autre établissement</h1>",
                      "<address>13 Rue des Fleurs, 12345 Ville-des-Bois</address>"):
            self.assertFalse(visible_venue_identity_matches(
                GROUP, CANDIDATE, page(extra=extra)))

    def test_other_structured_place_cannot_be_overridden_by_visible_page(self):
        other = ('<script type="application/ld+json">'
                 '{"@type":"Place","name":"Une autre médiathèque",'
                 '"address":{"streetAddress":"13 Rue des Chênes",'
                 '"postalCode":"12345","addressLocality":"Ville-des-Bois"}}'
                 '</script>')
        r = official_venue_page_proof(
            GROUP, CANDIDATE, BAN, URL,
            page(extra=other), HOSTS)
        self.assertFalse(r["official_identity_verified"])
        self.assertEqual(r["status"], "different_structured_place_identity")

    def test_schema_org_conflict_never_overridden_by_visible_text(self):
        structured = ('<script type="application/ld+json">'
                      '{"@type":"Place","name":"Maison des enfants",'
                      '"address":{"streetAddress":"13 Rue des Chênes",'
                      '"postalCode":"12345","addressLocality":"Ville-des-Bois"}}'
                      '</script>')
        r = official_venue_page_proof(
            GROUP, CANDIDATE, BAN, URL,
            page(extra=structured), HOSTS)
        self.assertFalse(r["official_identity_verified"])
        self.assertEqual(r["status"], "official_address_or_geo_conflict")

    def test_schema_event_does_not_certify_venue_without_visible_address(self):
        structured = ('<script type="application/ld+json">'
                      '{"@type":"Event","name":"Maison des enfants"}'
                      '</script>')
        r = official_venue_page_proof(
            GROUP, CANDIDATE, BAN, URL,
            "<html><h1>Maison des enfants</h1>" + structured + "</html>",
            HOSTS)
        self.assertFalse(r["official_identity_verified"])

    def test_address_with_extra_contact_data_does_not_false_positive(self):
        self.assertFalse(visible_venue_identity_matches(
            GROUP, CANDIDATE,
            page(address="12 Rue des Chênes, 12345 Ville-des-Bois - "
                         "tél. 04 00 00 00 00")))


if __name__ == "__main__":
    unittest.main()
