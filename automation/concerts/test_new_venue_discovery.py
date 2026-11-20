"""Unknown venues must become private, verifiable discoveries, never discarded.

Completely synthetic independent official/OSM fixtures: no real addresses,
outbound network requests, approvals or publication.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import discover
import triage
import dynamic_venue_evidence_preflight as preview

DAY = dt.date(2026, 11, 20)
SOURCE = {
    "name": "Salle du Nord", "city": "Lille", "department": "59",
    "url": "https://official-stage.example/agenda/",
}
EVENT_URL = "https://official-stage.example/evenements/date-inconnue-2027/"
OSM = "https://www.openstreetmap.org/node/874321987"
OSM_API = "https://api.openstreetmap.org/api/0.6/node/874321987.json"

def event(*, venue="Place des Épreuves", city="Paris",
          postcode="75007", country="FR", named=True, genre="Death Metal"):
    return {
        "@type": "MusicEvent", "name": "Groupe Alpha + Groupe Beta",
        "url": EVENT_URL, "startDate": "2027-07-19T20:00:00+02:00",
        "genre": [genre],
        "performer": [
            {"@type": "MusicGroup", "name": "Groupe Alpha"},
            {"@type": "MusicGroup", "name": "Groupe Beta"},
        ] if named else [{"@type": "Organization", "name": "Unknown"}],
        "location": {
            "@type": "Place", "name": venue, "sameAs": OSM,
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "1 avenue des Épreuves",
                "postalCode": postcode,
                "addressLocality": city, "addressRegion": "Île-de-France",
                "addressCountry": country,
            },
        },
    }

def proposal(raw=None):
    raw = raw if raw is not None else event()
    return discover.venue_candidate(
        raw, SOURCE, EVENT_URL, set(), "2026-11-20")

def catalogue(venues=None):
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "events": [], "artists": [], "venues": venues or [],
    }

class UnknownLocationDiscoveryTests(unittest.TestCase):
    def test_offsite_is_archived_as_new_venue_not_silently_refused(self):
        p = proposal()
        self.assertIsNotNone(p)
        self.assertEqual(p["source"], "agenda_officiel_lieu_a_verifier")
        self.assertEqual(p["venue"], "Place des Épreuves")
        self.assertEqual(p["city"], "Paris")
        self.assertEqual(p["department"], "75")
        self.assertTrue(p["venueOutsideSource"])
        self.assertTrue(p["newVenueToReview"])
        self.assertFalse(p["publicationAllowed"])
        self.assertEqual(p["sourcePage"], EVENT_URL)
        rows, _, counts = triage.classify([p], catalogue())
        self.assertEqual(counts["genre_tag_review"], 1)
        self.assertTrue(rows[0]["newVenueToReview"])
        self.assertEqual(rows[0]["venueDiscoveryReason"],
                         "not_exactly_in_public_catalogue")

    def test_missing_postcode_is_research_not_rejected_and_not_approved(self):
        p = proposal(event(postcode=""))
        self.assertIsNotNone(p)
        self.assertEqual(p["department"], "")
        self.assertTrue(p["officialLocationIncomplete"])
        self.assertTrue(p["newVenueToReview"])
        self.assertFalse(p["publicationAllowed"])

    def test_same_venue_name_unknown_in_catalogue_is_flagged(self):
        raw = event(venue=SOURCE["name"], city=SOURCE["city"], postcode="59000")
        p = proposal(raw)
        self.assertEqual(p["source"], "agenda_officiel_structuré")
        rows, _, _ = triage.classify([p], catalogue())
        self.assertTrue(rows[0]["newVenueToReview"])
        known = [{"id": "known-hall", "name": SOURCE["name"],
                  "city": SOURCE["city"], "department": SOURCE["department"]}]
        rows, _, _ = triage.classify([p], catalogue(known))
        self.assertFalse(rows[0].get("newVenueToReview", False))

    def test_offsite_can_be_known_without_erasing_distinct_origin(self):
        known = [{"id": "place-known", "name": "Place des Épreuves",
                  "city": "Paris", "department": "75"}]
        rows, _, _ = triage.classify([proposal()], catalogue(known))
        self.assertFalse(rows[0]["newVenueToReview"])
        self.assertTrue(rows[0]["venueOutsideSource"])

    def test_untrusted_offsite_pages_and_missing_named_performer_are_held(self):
        invalid = [
            (event(named=False), SOURCE, EVENT_URL),
            (event(country="BE"), SOURCE, EVENT_URL),
            (event(), SOURCE, "https://external.example/evenements/fake/"),
            (event(), {**SOURCE, "url": "https://external.example/agenda/"}, EVENT_URL),
            ({**event(), "@type": "Organization"}, SOURCE, EVENT_URL),
        ]
        for raw, source, page_url in invalid:
            with self.subTest(raw_type=raw.get("@type"), url=page_url):
                self.assertIsNone(discover.venue_candidate(
                    raw, source, page_url, set(), "2026-11-20"))

    def test_source_linked_new_site_gets_independent_proof_but_no_approval(self):
        discovered = triage.classify([proposal()], catalogue())[0][0]
        registry = {
            "schema": preview.INTAKE,
            "items": {"synthetic": {
                "candidate": discovered, "status": "pending_review",
                "stableObservations": 2,
            }},
        }
        sources = {"schema": preview.SOURCES, "venues": [SOURCE]}
        approved = {"schema": preview.APPROVALS, "approvals": []}
        before = copy.deepcopy((registry, sources, approved))
        calls = []
        def official_fetch(url, **kwargs):
            calls.append(url)
            if url != EVENT_URL:
                raise AssertionError("Unexpected official URL")
            return ('<script type="application/ld+json">'
                    + json.dumps(event(), ensure_ascii=False)
                    + '</script>'), url
        osm = json.dumps({"elements": [{
            "id": 874321987, "type": "node", "lat": 48.858,
            "lon": 2.294, "tags": {
                "name": "Place des Épreuves", "addr:city": "Paris",
                "addr:postcode": "75007", "addr:country": "FR",
            },
        }]})
        def geo_fetch(url, cap):
            calls.append(url)
            self.assertEqual(url, OSM_API)
            return osm, url
        report = preview.build(
            registry, sources, catalogue(), approved, DAY,
            fetch=official_fetch, robots=lambda url, cache: True,
            geo_fetch=geo_fetch, scan_slot=2)
        self.assertEqual(calls, [EVENT_URL, OSM_API])
        self.assertEqual(report["newSitesIndependentlyLocatedPrivateOnly"], 1)
        self.assertEqual(report["newVenueCandidates"], 1)
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertFalse(report["publicationAllowed"])
        self.assertFalse(report["publisherTrustGranted"])
        site = report["results"][0]["proposedSite"]
        self.assertEqual(site["name"], "Place des Épreuves")
        self.assertEqual(site["geoSource"], OSM)
        self.assertFalse(site["publicationAllowed"])
        self.assertEqual(before, (registry, sources, approved))
        self.assertEqual(catalogue()["venues"], [])

if __name__ == "__main__":
    unittest.main()
