"""Adversarial fake data for generic independent venue geocoding, no network."""
import json
import copy
import unittest
from pathlib import Path
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_geo_bridge import (
    review_independent_geo, review_direct_with_independent_geo,
)

LEAD = {"venue": "Médiathèque des Familles", "city": "Rouen"}
EVENT = {"location": {
    "name": "Médiathèque des Familles", "adminLevel4": "Rouen",
    "countryCode": "FR", "latitude": 49.42621, "longitude": 1.09697,
}}
SOURCE = {
    "approved_host": "rouen.fr",
    "exact_url": "https://rouen.fr/lieux/mediatheque",
}
NODE = {
    "@context": "https://schema.org",
    "@type": ["Place", "Library"],
    "name": "Médiathèque des Familles",
    "alternateName": "Bibliothèque des Familles",
    "address": {
        "@type": "PostalAddress", "streetAddress": "42 rue Henri II Plantagenet",
        "postalCode": "76100", "addressLocality": "Rouen",
        "addressCountry": "FR",
    },
}
def html(node=None):
    payload = NODE if node is None else node
    return "<html><body><h1>La médiathèque</h1><script type='application/ld+json'>" + json.dumps(payload) + "</script></body></html>"

PAGE = {"url": SOURCE["exact_url"], "html": html()}
GEO_URL = "https://data.geopf.fr/geocodage/search?q=" + quote(
    "42 rue Henri II Plantagenet 76100 Rouen") + "&limit=2"
FEATURE = {
    "type": "Feature",
    "properties": {"type": "housenumber", "score": 0.972,
                   "housenumber": "42", "street": "rue Henri II Plantagenet",
                   "postcode": "76100", "city": "Rouen", "citycode": "76540"},
    "geometry": {"type": "Point", "coordinates": [1.09697, 49.42621]},
}
BAN = {"type": "FeatureCollection", "features": [FEATURE]}


def review(**changes):
    kwargs = {
        "lead": copy.deepcopy(LEAD), "api_event": copy.deepcopy(EVENT),
        "reviewed_source": copy.deepcopy(SOURCE), "official_page": copy.deepcopy(PAGE),
        "geocoder_request_url": GEO_URL, "geojson": copy.deepcopy(BAN),
    }
    kwargs.update(changes)
    return review_independent_geo(**kwargs)


class IndependentGeoContract(unittest.TestCase):
    def test_exact_three_way_municipal_ban_openagenda_match_is_not_approval(self):
        result = review()
        self.assertTrue(result["geo_evidence_consistent"], result["reason"])
        self.assertEqual(result["registered_venue"]["city"], "Rouen")
        self.assertIn("mediatheque des familles", result["registered_venue"]["aliases"])
        self.assertEqual(result["registered_venue"]["lat"], 49.42621)
        self.assertFalse(result["publisher_connected"])
        self.assertFalse(result["approval_granted"])
        self.assertEqual(result["public_writes"], 0)

    def test_reviewed_page_must_be_exact_and_not_openagenda_or_forged_hostname(self):
        variants = (
            dict(reviewed_source=dict(SOURCE, approved_host="rouen.fr.evil.test")),
            dict(reviewed_source=dict(SOURCE, approved_host="openagenda.com")),
            dict(reviewed_source=dict(SOURCE, exact_url="http://rouen.fr/lieux/mediatheque")),
            dict(reviewed_source=dict(SOURCE, exact_url="https://rouen.fr.evil.test/path")),
            dict(reviewed_source=dict(SOURCE, exact_url="https://127.0.0.1/lieu")),
            dict(official_page=dict(PAGE, url="https://rouen.fr/lieux/faux")),
            dict(reviewed_source=dict(SOURCE, exact_url="https://rouen.fr/lieux/mediatheque#x")),
            dict(reviewed_source={}),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertFalse(review(**variant)["geo_evidence_consistent"])

    def test_official_jsonld_must_report_exact_address_and_venue(self):
        for bad in (
            dict(NODE, name="Autre bibliothèque", alternateName=[]),
            dict(NODE, address=dict(NODE["address"], streetAddress="rue sans numero")),
            dict(NODE, address=dict(NODE["address"], postalCode="76000")),
            dict(NODE, address=dict(NODE["address"], addressLocality="Paris")),
            dict(NODE, address=dict(NODE["address"], addressCountry="DE")),
            dict(NODE, **{"@type": "Event"}),
        ):
            with self.subTest(node=bad):
                self.assertFalse(review(official_page=dict(PAGE, html=html(bad)))[
                    "geo_evidence_consistent"])

    def test_conflicting_duplicate_official_addresses_are_held(self):
        conflicting = copy.deepcopy(NODE)
        conflicting["address"]["streetAddress"] = "43 rue Henri II Plantagenet"
        graph = {"@graph": [NODE, conflicting]}
        result = review(official_page=dict(PAGE, html=html(graph)))
        self.assertEqual(result["reason"], "official_address_not_exact_or_ambiguous")

    def test_geocoder_must_query_only_official_address(self):
        for url in (
            GEO_URL.replace("42%20", "43%20"),
            GEO_URL.replace("data.geopf.fr", "data.geopf.fr.evil.test"),
            GEO_URL.replace("limit=2", "limit=9999"),
            GEO_URL + "&redirect=https://evil.test",
            "http://data.geopf.fr/geocodage/search?q=a",
            "https://data.geopf.fr/geocodage/search?q=Rue%20X",
        ):
            with self.subTest(url=url):
                self.assertFalse(review(geocoder_request_url=url)[
                    "geo_evidence_consistent"])

    def test_exact_housenumber_minimum_score_city_postcode_and_insee(self):
        for prop in (
            {"type": "street"}, {"score": 0.89}, {"score": "0.99"},
            {"city": "Paris"}, {"postcode": "76000"},
            {"citycode": "!!!"}, {"housenumber": "43"},
            {"street": "rue des Lilas"},
        ):
            with self.subTest(properties=prop):
                bad = copy.deepcopy(BAN)
                bad["features"][0]["properties"].update(prop)
                self.assertEqual(review(geojson=bad)["reason"],
                                 "no_exact_housenumber_geocode")

    def test_far_or_malformed_openagenda_coordinates_never_pass(self):
        for coords in ((49.43, 1.09), (float("nan"), 1.09697), ("49", 1.09)):
            bad = copy.deepcopy(EVENT)
            bad["location"]["latitude"], bad["location"]["longitude"] = coords
            self.assertFalse(review(api_event=bad)["geo_evidence_consistent"])

    def test_bad_geometry_and_ambiguous_housenumber_are_held(self):
        ban = copy.deepcopy(BAN)
        ban["features"][0]["geometry"]["coordinates"] = [1.095, 49.43]
        self.assertEqual(review(geojson=ban)["reason"],
                         "openagenda_point_not_matched_to_ban")
        ban = copy.deepcopy(BAN)
        other = copy.deepcopy(FEATURE)
        other["geometry"]["coordinates"] = [1.10, 49.43]
        ban["features"].append(other)
        self.assertEqual(review(geojson=ban)["reason"],
                         "ambiguous_geocoded_housenumber")
        ban["features"] = [FEATURE] * 21
        self.assertEqual(review(geojson=ban)["reason"],
                         "invalid_geocoder_response")

    def test_alias_allowed_only_when_independent_institution_names_it(self):
        alternative = dict(LEAD, venue="Bibliothèque des Familles")
        event = copy.deepcopy(EVENT)
        event["location"]["name"] = "Bibliothèque des Familles"
        self.assertTrue(review(lead=alternative, api_event=event)[
            "geo_evidence_consistent"])
        restricted = dict(NODE, alternateName=[])
        self.assertFalse(review(
            lead=alternative, api_event=event,
            official_page=dict(PAGE, html=html(restricted))
        )["geo_evidence_consistent"])

    def test_other_country_and_inconsistent_overseas_codes_block(self):
        e = copy.deepcopy(EVENT)
        e["location"]["countryCode"] = "DE"
        self.assertFalse(review(api_event=e)["geo_evidence_consistent"])
        e["location"]["countryCode"] = "GP"
        e["location"]["adminLevel1"] = "Guadeloupe"
        e["location"]["adminLevel2"] = "Martinique"
        self.assertFalse(review(api_event=e)["geo_evidence_consistent"])

    def test_no_intake_approval_flag_can_bypass_independent_proof(self):
        lead = dict(LEAD, approved=True, gps_verified=True, lat=49.42621,
                    lng=1.09697)
        self.assertTrue(review(lead=lead)["geo_evidence_consistent"])
        fake_page = dict(PAGE, html="<html>GPS validé</html>")
        check = review(lead=lead, official_page=fake_page)
        self.assertFalse(check["geo_evidence_consistent"])
        self.assertFalse(check["approval_granted"])
        self.assertEqual(check["public_writes"], 0)



class CombinedReadOnlyGeoAndDirectEvidence(unittest.TestCase):
    def data(self):
        lead = dict(LEAD,
            source_url="https://openagenda.com/fr/rouen-test/events/12345678_atelier",
            external_id="12345678", date_start="2026-12-05",
            date_end="2026-12-05", title="Atelier jeunesse")
        ev = dict(EVENT,
            uid=12345678, state=2, status=1,
            attendanceMode=1, timezone="Europe/Paris",
            title={"fr": "Atelier jeunesse"},
            description={"fr": "Atelier créatif pour enfants"},
            rights={"license": {"id": "etalab-2.0"},
                    "licensor": {"name": "Institution fictive"}},
            timings=[{"begin": "2026-12-05T14:00:00+0100",
                      "end": "2026-12-05T15:00:00+0100"}])
        agenda = {"agenda_slug": "rouen-test", "agenda_uid": "919191",
                  "timezone": "Europe/Paris"}
        return lead, ev, agenda

    def test_geocode_can_feed_direct_api_verification_without_publisher(self):
        from datetime import date
        lead, ev, agenda = self.data()
        result = review_direct_with_independent_geo(
            lead, ev, agenda, SOURCE, PAGE, GEO_URL, BAN,
            date(2026, 11, 18))
        self.assertTrue(result["geography_verified"])
        self.assertTrue(result["direct_source_structurally_valid"], result["reason"])
        self.assertFalse(result["publisher_connected"])
        self.assertFalse(result["approval_granted"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("registered_venue", result)
        self.assertNotIn("source_url", result)

    def test_forged_geo_and_adult_only_api_record_fail_separately(self):
        from datetime import date
        lead, ev, agenda = self.data()
        fake_geo = dict(PAGE, html="<html><body>Lieu inventé</body></html>")
        absent = review_direct_with_independent_geo(
            lead, ev, agenda, SOURCE, fake_geo, GEO_URL, BAN,
            date(2026, 11, 18))
        self.assertFalse(absent["geography_verified"])
        self.assertFalse(absent["direct_source_structurally_valid"])
        ev = dict(ev, description={"fr": "Réservé aux adultes uniquement"})
        invalid = review_direct_with_independent_geo(
            lead, ev, agenda, SOURCE, PAGE, GEO_URL, BAN,
            date(2026, 11, 18))
        self.assertTrue(invalid["geography_verified"])
        self.assertFalse(invalid["direct_source_structurally_valid"])
        self.assertEqual(invalid["reason"], "family_audience_not_in_source_record")
        self.assertFalse(invalid["approval_granted"])


if __name__ == "__main__":
    unittest.main()
