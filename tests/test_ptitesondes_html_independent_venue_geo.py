"""Offline adversarial diagnostics of first-party venue page + independent BAN.

No OpenAgenda event, private queue, publishing or network is required.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_independent_venue_geo import (
    diagnose_html_independent_venue, SCHEMA,
)

SOURCE = "https://rouen.fr/lieux/bibliotheque-test"
LEAD = {
    "venue": "Bibliothèque des familles",
    "city": "Rouen",
    "title": "Atelier lecture jeunesse",
    "source_url": "https://rouen.fr/evenement/lecture",
    "date_start": "2026-11-22",
    "start_local": "15:00",
}
VENUE = {
    "city": "Rouen",
    "aliases": ["Bibliothèque des familles"],
    "lat": 49.42621,
    "lng": 1.09697,
    "official": SOURCE,
    "geo_source": "https://www.openstreetmap.org/way/54321",
}
PLACE = {
    "@type": "Library",
    "name": "Bibliothèque des familles",
    "address": {
        "@type": "PostalAddress",
        "streetAddress": "42 rue Henri II Plantagenet",
        "postalCode": "76100",
        "addressLocality": "Rouen",
        "addressCountry": "FR",
    },
}
HTML = ("<html><body><h1>Bibliothèque</h1>"
        "<script type='application/ld+json'>"
        + json.dumps(PLACE, ensure_ascii=False) + "</script></body></html>")
BAN = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "type": "housenumber", "score": 0.972, "housenumber": "42",
            "street": "rue Henri II Plantagenet", "postcode": "76100",
            "city": "Rouen", "citycode": "76540",
        },
        "geometry": {"type": "Point", "coordinates": [1.09697, 49.42621]},
    }],
}
QUERY = "https://data.geopf.fr/geocodage/search?q=" + quote(
    "42 rue Henri II Plantagenet 76100 Rouen") + "&limit=2"


def context(venues=None, public=None):
    return {
        "legacy_venues": [deepcopy(VENUE)] if venues is None else venues,
        "public_places": [] if public is None else public,
        "historical_catalogue": {"updated_at": "2026-11-19T15:00:00+01:00",
                                 "events": []},
    }


def diagnose(lead=None, registry=None, html=HTML, ban=None, trace=None,
             official_page_url=SOURCE):
    seen = [] if trace is None else trace

    def official_reader(pin):
        seen.append("official")
        assert pin == {"approved_host": "rouen.fr", "exact_url": SOURCE}
        return {"url": official_page_url, "html": html}

    def geo_reader(query):
        seen.append("ban")
        assert query == QUERY
        return deepcopy(BAN) if ban is None else ban

    return diagnose_html_independent_venue(
        deepcopy(LEAD) if lead is None else lead,
        context() if registry is None else registry,
        venue_reader=official_reader, ban_reader=geo_reader,
    )


class IndependentVenueForHTML(unittest.TestCase):
    def test_exact_reviewed_venue_first_party_address_and_ban_concordant(self):
        trace = []
        r = diagnose(trace=trace)
        self.assertEqual(trace, ["official", "ban"])
        self.assertEqual(r["schema"], SCHEMA)
        self.assertEqual(r["reason"],
                         "independent_official_address_ban_registry_concordant")
        self.assertTrue(r["official_venue_address_present"])
        self.assertTrue(r["independent_ban_housenumber_matched"])
        self.assertTrue(r["registry_coordinates_concordant"])
        self.assertTrue(r["geometry_evidence_consistent"])
        for field in ("event_session_attested", "organizer_ownership_attested",
                      "family_age_access_verified", "rights_reviewed",
                      "publisher_connected", "publication_ready", "approval_granted"):
            self.assertFalse(r[field])
        self.assertEqual(r["public_writes"], 0)
        report = json.dumps(r)
        for fragment in ("Rouen", "49.426", "rouen.fr", "Bibliothèque",
                         "54321", "source_url", "latitude"):
            self.assertNotIn(fragment, report)

    def test_unreviewed_missing_ambiguous_and_spoofed_source_do_not_fetch(self):
        cases = [
            dict(LEAD, venue="Bibliothèque des familles annexe"),
            dict(LEAD, city="Paris"),
            dict(LEAD, venue="Bibliothèque des famille"),
        ]
        for lead in cases:
            with self.subTest(lead=lead):
                trace = []
                r = diagnose(lead=lead, trace=trace)
                self.assertEqual(r["reason"],
                                 "reviewed_venue_absent_ambiguous_or_untrusted")
                self.assertEqual(trace, [])
        forged = dict(LEAD, official="https://evil.test/inject",
                      lat=0, lng=0, approved=True)
        r = diagnose(lead=forged)
        self.assertTrue(r["geometry_evidence_consistent"])
        # The forged lead fields were deliberately ignored; no approval.
        self.assertFalse(r["approval_granted"])
        trace = []
        r = diagnose(registry=context(public=[deepcopy(VENUE)]), trace=trace)
        self.assertEqual(r["reason"],
                         "reviewed_venue_absent_ambiguous_or_untrusted")
        self.assertEqual(trace, [])

    def test_false_registry_provenance_is_never_source_of_geo(self):
        for venue in (
            dict(VENUE, geo_source=SOURCE),
            dict(VENUE, official="http://rouen.fr/untrusted"),
            dict(VENUE, lat=float("nan")),
            dict(VENUE, lat=90.3),
        ):
            with self.subTest(venue=venue):
                trace = []
                r = diagnose(registry=context(venues=[venue]), trace=trace)
                self.assertFalse(r["geometry_evidence_consistent"])
                self.assertEqual(trace, [])

    def test_wrong_exact_venue_page_and_missing_jsonld_are_held(self):
        wrong = diagnose(official_page_url=SOURCE + "?redirect=1")
        self.assertEqual(wrong["reason"], "official_venue_page_unavailable")
        no_address = diagnose(html="<html><body><h1>Aucune adresse</h1></body></html>")
        self.assertEqual(no_address["reason"],
                         "official_venue_address_not_structured")
        no_housenumber = deepcopy(PLACE)
        no_housenumber["address"]["streetAddress"] = "rue Henri II Plantagenet"
        self.assertEqual(diagnose(html="<html><body><script type='application/ld+json'>"
                                        + json.dumps(no_housenumber)
                                        + "</script></body></html>")["reason"],
                         "official_venue_address_not_structured")

    def test_wrong_venue_or_conflicting_addresses_fail_closed(self):
        wrong = deepcopy(PLACE)
        wrong["name"] = "Une autre bibliothèque"
        page = "<html><body><script type='application/ld+json'>" + json.dumps(
            wrong) + "</script></body></html>"
        self.assertEqual(diagnose(html=page)["reason"],
                         "official_venue_address_not_structured")
        other = deepcopy(PLACE)
        other["address"]["streetAddress"] = "43 rue Henri II Plantagenet"
        graph = {"@graph": [PLACE, other]}
        page = "<html><body><script type='application/ld+json'>" + json.dumps(
            graph) + "</script></body></html>"
        self.assertEqual(diagnose(html=page)["reason"],
                         "official_venue_address_not_structured")

    def test_no_ban_exact_number_score_and_feature_rejected(self):
        for changes in (
            {"housenumber": "43"}, {"street": "rue fictive"},
            {"postcode": "76000"}, {"city": "Paris"}, {"type": "street"},
            {"score": 0.89}, {"score": True}, {"citycode": "bad"},
        ):
            with self.subTest(changes=changes):
                geo = deepcopy(BAN)
                geo["features"][0]["properties"].update(changes)
                r = diagnose(ban=geo)
                self.assertEqual(r["reason"], "ban_housenumber_missing_or_ambiguous")
                self.assertFalse(r["geometry_evidence_consistent"])

    def test_ban_spoofed_coordinates_or_ambiguous_exact_points(self):
        cases = []
        bad = deepcopy(BAN)
        bad["features"][0]["geometry"]["coordinates"] = [2.3, 48.8]
        cases.append((bad, "ban_conflicts_with_reviewed_venue"))
        bad = deepcopy(BAN)
        bad["features"].append(deepcopy(bad["features"][0]))
        bad["features"][1]["geometry"]["coordinates"] = [2.3, 48.8]
        cases.append((bad, "ban_housenumber_missing_or_ambiguous"))
        bad = deepcopy(BAN)
        bad["features"][0]["geometry"]["coordinates"] = [0, 0]
        cases.append((bad, "ban_housenumber_missing_or_ambiguous"))
        for geo, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(diagnose(ban=geo)["reason"], reason)

    def test_bad_context_and_bad_readers_fail_closed(self):
        for bad in (None, {}, {"legacy_venues": [], "public_places": []},
                    context(venues="not reviewed"), context(public="forged")):
            with self.subTest(bad=str(type(bad))):
                r = diagnose(registry=bad)
                self.assertFalse(r["geometry_evidence_consistent"])
        out = diagnose_html_independent_venue(
            LEAD, context(), venue_reader=None, ban_reader=None)
        self.assertEqual(out["reason"], "independent_readers_unavailable")
        self.assertFalse(out["approval_granted"])

    def test_official_and_ban_fetch_errors_are_redacted_and_do_not_publish(self):
        def unavailable(_):
            raise OSError("Private venue URL and error payload")
        a = diagnose_html_independent_venue(
            LEAD, context(), venue_reader=unavailable, ban_reader=lambda _: BAN)
        b = diagnose_html_independent_venue(
            LEAD, context(), venue_reader=lambda _: {
                "url": SOURCE, "html": HTML}, ban_reader=unavailable)
        for result in (a, b):
            self.assertEqual(result["reason"], "independent_source_or_ban_unavailable")
            self.assertEqual(result["public_writes"], 0)
            self.assertNotIn("Private", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
