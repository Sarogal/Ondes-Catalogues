"""Offline adversarial checks for independently authenticated official venue HTML."""
import sys
import unittest
from pathlib import Path
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_generic_venue_official_proof import (
    official_venue_page_proof,
)

GROUP = {"city": "Ville-des-Bois", "venue": "Maison des enfants"}
CANDIDATE = {
    "city": "Ville-des-Bois", "venue": "Maison des enfants",
    "postcode": "12345", "housenumber": "12",
    "street": "Rue des Chênes", "lat_osm_hint": 44.50,
    "lng_osm_hint": 2.25,
}
BAN = {"address_correlated": True, "gps_verified": False,
       "publication_ready": False}
URL = "https://ville-des-bois.fr/lieux/maison-des-enfants"
HOSTS = frozenset({"ville-des-bois.fr"})

def page(name="Maison des enfants", street="12 Rue des Chênes",
         postcode="12345", city="Ville-des-Bois", kind="Place",
         latitude=None):
    import json
    node = {
        "@context": "https://schema.org", "@type": kind, "name": name,
        "address": {"@type": "PostalAddress", "streetAddress": street,
                    "postalCode": postcode, "addressLocality": city,
                    "addressCountry": "FR"},
    }
    if latitude is not None:
        node["geo"] = {"latitude": latitude, "longitude": 2.25}
    return "<html><body><script type='application/ld+json'>" + (
        json.dumps(node, ensure_ascii=False)) + (
        "</script><p>Page officielle du lieu</p></body></html>")


class GenericOfficialVenueProofTests(unittest.TestCase):
    def proof(self, html=None, group=GROUP, candidate=CANDIDATE, ban=BAN,
              url=URL, hosts=HOSTS):
        return official_venue_page_proof(
            group, candidate, ban, url, page() if html is None else html,
            hosts,
        )

    def test_exact_official_place_requires_independently_approved_host(self):
        r = self.proof()
        self.assertTrue(r["official_identity_verified"])
        self.assertTrue(r["location_evidence_complete_for_private_review"])
        self.assertFalse(r["event_sessions_verified"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(r["public_writes"], 0)

    def test_unapproved_or_malicious_hosts_fail(self):
        for url in (
            "https://ville-des-bois.fr.attacker.invalid/lieux/",
            "https://ville-des-bois.fr@evil.invalid/lieux/",
            "http://ville-des-bois.fr/lieux/",
            "https://ville-des-bois.fr:8080/lieux/",
            "https://openagenda.com/ville-des-bois/lieux",
        ):
            with self.subTest(url=url):
                self.assertFalse(self.proof(url=url)["official_identity_verified"])
        self.assertFalse(self.proof(hosts=frozenset({"other.fr"}))["official_identity_verified"])
        self.assertFalse(self.proof(hosts=())["official_identity_verified"])

    def test_missing_or_untrusted_ban_fails(self):
        for change in ({"address_correlated": False},
                       {"gps_verified": True},
                       {"publication_ready": True}):
            bad = {**BAN, **change}
            self.assertFalse(self.proof(ban=bad)["official_identity_verified"])

    def test_name_city_street_house_and_postcode_must_match(self):
        for p in (
            {"name": "Maison de la musique"},
            {"street": "13 Rue des Chênes"},
            {"postcode": "54321"},
            {"city": "Autre-Ville"},
        ):
            with self.subTest(patch=p):
                r = self.proof(html=page(**p))
                self.assertFalse(r["official_identity_verified"])

    def test_official_conflicting_geocoordinates_refused(self):
        self.assertFalse(self.proof(html=page(latitude=44.51))["official_identity_verified"])
        self.assertTrue(self.proof(html=page(latitude=44.50))["official_identity_verified"])

    def test_hidden_event_jsonld_is_not_a_venue(self):
        self.assertFalse(self.proof(html=page(kind="Event"))["official_identity_verified"])

    def test_jsonld_in_graph_works_without_city_allowlist(self):
        raw = page().split("<script type='application/ld+json'>")[1].split("</script>")[0]
        wrapped = ("<html><script type='application/ld+json'>"
                   '{"@graph":[' + raw + "]}</script></html>")
        self.assertTrue(self.proof(html=wrapped)["official_identity_verified"])

    def test_multiple_same_named_locations_is_ambiguous(self):
        a = page()
        b = page(street="13 Rue des Chênes")
        combined = a + b
        self.assertFalse(self.proof(html=combined)["official_identity_verified"])

    def test_source_html_with_only_visible_text_is_not_schema_proof(self):
        html = ("<html><body><p>Maison des enfants 12 Rue des Chênes, "
                "12345 Ville-des-Bois</p></body></html>")
        self.assertFalse(self.proof(html=html)["official_identity_verified"])

    def test_no_page_no_venue_or_no_ban_cannot_grant_approval(self):
        bad_candidate = deepcopy(CANDIDATE)
        bad_candidate["venue"] = "Autre lieu"
        self.assertFalse(self.proof(candidate=bad_candidate)["official_identity_verified"])
        self.assertFalse(self.proof(html="")["official_identity_verified"])
        self.assertFalse(self.proof(ban=None)["official_identity_verified"])


if __name__ == "__main__":
    unittest.main()
