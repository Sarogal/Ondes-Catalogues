"""Synthetic offline integration tests for automatic paired event-site approvals.

Every official page and OSM response is invented test data: never interpreted
as a real concert, location observation or production approval.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import concerts_cloud_sync as publisher
import approval_preflight as gate
import event_site_pair_recheck as reviewer
import official_recheck

DAY = dt.date(2026, 11, 19)
DATE = "2027-05-17"
EVENT = "https://7weeks.fr/concerts/fixture-2027-metal-park/"
OSM = "https://www.openstreetmap.org/node/123456789"
API = "https://api.openstreetmap.org/api/0.6/node/123456789.json"


def fixture(names=("7WEEKS", "NEW METAL SUPPORT"), genre="Heavy Metal"):
    raw = {
        "@type": "MusicEvent", "url": EVENT,
        "name": " + ".join(names),
        "startDate": DATE + "T20:00:00+02:00",
        "genre": [genre],
        "performer": [{"@type": "MusicGroup", "name": n} for n in names],
        "location": {"@type": "Place", "name": "Esplanade des Tests",
                     "sameAs": OSM,
                     "address": {"@type": "PostalAddress",
                                 "streetAddress": "Avenue des Essais",
                                 "postalCode": "75007",
                                 "addressLocality": "Paris",
                                 "addressRegion": "Île-de-France",
                                 "addressCountry": "FR"}},
    }
    candidate = {
        "candidateId": "synthetic-tour-2027",
        "source": "artist_official_tour",
        "sourceUrl": "https://7weeks.fr/concerts/",
        "eventDetailUrl": EVENT, "artistId": "7weeks",
        "sourceRole": "artist_official",
        "date": DATE, "name": raw["name"], "leadArtist": "7WEEKS",
        "venue": "Esplanade des Tests", "city": "Paris",
        "classification": [], "reviewBucket": "genre_unknown",
        "newVenueToReview": True,
        "reviewRequired": True, "publicationAllowed": False,
        "possibleExistingConcert": False,
    }
    cat = {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "artists": [{"id": "7weeks", "name": "7WEEKS", "aliases": []}],
        "venues": [], "events": [],
    }
    osm_payload = {"version": "0.6", "elements": [{
        "id": 123456789, "type": "node", "lat": 48.858,
        "lon": 2.294, "tags": {
            "name": "Esplanade des Tests",
            "addr:city": "Paris", "addr:postcode": "75007",
            "addr:country": "FR",
        }
    }]}
    return candidate, raw, cat, osm_payload


def fake_fetch(raw, osm_payload, calls):
    def fetch(url, limit):
        calls.append(url)
        if url == EVENT:
            return '<script type="application/ld+json">' + json.dumps(
                raw, ensure_ascii=False) + '</script>', url
        if url == API:
            return json.dumps(osm_payload), url
        raise AssertionError("Unexpected outgoing fetch: " + str(url))
    return fetch


class PairedNewSiteIntegrationTests(unittest.TestCase):
    def test_official_event_and_independently_read_site_create_exact_pair(self):
        lead, raw, cat, osm = fixture()
        calls = []
        app, venue = reviewer.verify(
            lead, cat, DAY, fetch=fake_fetch(raw, osm, calls))
        self.assertEqual(calls, [EVENT, API])
        self.assertEqual(app["event"]["artistIds"], ["7weeks", "new-metal-support"])
        self.assertEqual(app["newArtists"],
                         [{"id": "new-metal-support", "name": "NEW METAL SUPPORT"}])
        self.assertEqual(venue["eventBinding"]["eventId"], app["event"]["id"])
        self.assertEqual(venue["venue"]["city"], "Paris")
        self.assertEqual(venue["venue"]["geoSource"], OSM)
        self.assertEqual(venue["venue"]["latitude"], 48.858)
        self.assertEqual(venue["venueKind"], "independent-event-site-v1")
        self.assertEqual(venue["reviewedBy"], "independent-official-verifier")
        self.assertNotIn("venueKind", app)
        self.assertEqual(
            len(venue["officialEvidence"]), 2)

    def test_true_private_process_and_real_publisher_preflight_atomic(self):
        lead, raw, cat, osm = fixture()
        ledger = {
            "schema": publisher.SCHEMA,
            "approvals": [], "venueApprovals": [],
        }
        registry = {"items": {"synthetic": {
            "status": "pending_review", "stableObservations": 2,
            "candidate": lead,
        }}}
        proposed, report = official_recheck.process(
            registry, cat, ledger, DAY,
            fetch=lambda *_: self.fail("legacy verifier must not fetch"),
            site_fetch=fake_fetch(raw, osm, []))
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(report["newSiteApprovals"]), 1)
        self.assertEqual(len(proposed["approvals"]), 1)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        self.assertEqual(ledger["approvals"], [])
        self.assertEqual(ledger["venueApprovals"], [])
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        report = gate.validate_proposal(
            ledger, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(report["validatedByPublisher"])
        self.assertEqual(report["publishableEvents"], 1)
        self.assertEqual(report["newApprovals"], 1)

    def test_many_unknown_bands_not_capped(self):
        names = ("7WEEKS",) + tuple(f"NEW BAND {i:02d}" for i in range(9))
        lead, raw, cat, osm = fixture(names=names)
        event, venue = reviewer.verify(
            lead, cat, DAY, fetch=fake_fetch(raw, osm, []))
        self.assertEqual(len(event["event"]["artistIds"]), 10)
        self.assertEqual(len(event["newArtists"]), 9)
        self.assertEqual(venue["eventBinding"]["authorityArtistId"], "7weeks")

    def test_untrusted_promoter_and_redirect_never_read_geography(self):
        lead, raw, cat, osm = fixture()
        for change in (
            {"sourceUrl": "https://unknown.example/shows/"},
            {"eventDetailUrl": "https://untrusted.example/event/"},
            {"artistId": "unregistered-artist"},
            {"sourceRole": "promoter_official"},
            {"newVenueToReview": False},
            {"publicationAllowed": True},
            {"possibleExistingConcert": True},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    reviewer.verify({**lead, **change}, cat, DAY,
                                    fetch=lambda *_: self.fail(
                                        "Source must be rejected before HTTP"))
        bad = fake_fetch(raw, osm, [])
        def redirected(url, limit):
            page, _ = bad(url, limit)
            return page, "https://malicious.example/fake"
        with self.assertRaises(ValueError):
            reviewer.verify(lead, cat, DAY, fetch=redirected)

    def test_osm_identity_cannot_be_invented_from_postcode_or_map_pin(self):
        lead, raw, cat, osm = fixture()
        for change in (
            {"name": "Different Place"},
            {"addr:city": "Lyon"},
            {"addr:postcode": "69000"},
            {"addr:country": "BE"},
        ):
            with self.subTest(change=change):
                bad = copy.deepcopy(osm)
                bad["elements"][0]["tags"].update(change)
                with self.assertRaises(ValueError):
                    reviewer.verify(lead, cat, DAY,
                                    fetch=fake_fetch(raw, bad, []))
        for field in ("lat", "lon"):
            bad = copy.deepcopy(osm)
            del bad["elements"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                reviewer.verify(lead, cat, DAY,
                                fetch=fake_fetch(raw, bad, []))

    def test_fresh_event_mismatch_cancellation_wrong_genre_and_wrong_site_fail(self):
        lead, raw, cat, osm = fixture()
        bad_cases = (
            {"startDate": "2027-05-18T20:00:00+02:00"},
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"eventStatus": "https://schema.org/EventPostponed"},
            {"performer": [{"@type": "MusicGroup", "name": "OTHER BAND"}]},
            {"genre": ["Hardcore Techno"]},
            {"genre": ["Jazz"]},
            {"location": {**raw["location"],
                          "name": "Wrong Park"}},
            {"location": {**raw["location"],
                          "sameAs": "https://www.openstreetmap.org/search?q=Paris"}},
        )
        for update in bad_cases:
            with self.subTest(update=update), self.assertRaises(ValueError):
                reviewer.verify(lead, cat, DAY,
                                fetch=fake_fetch({**raw, **update}, osm, []))

    def test_one_day_instability_and_duplicate_cannot_enter_private_proposal(self):
        lead, raw, cat, osm = fixture()
        ledger = {"schema": publisher.SCHEMA,
                  "approvals": [], "venueApprovals": []}
        reg = {"items": {"synthetic": {
            "stableObservations": 1, "status": "pending_review",
            "candidate": lead,
        }}}
        proposed, report = official_recheck.process(
            reg, cat, ledger, DAY,
            fetch=lambda *_: self.fail("no network"),
            site_fetch=lambda *_: self.fail("no network"))
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(proposed, ledger)
        app, venue = reviewer.verify(
            lead, cat, DAY, fetch=fake_fetch(raw, osm, []))
        cat["events"].append(app["event"])
        with self.assertRaises(ValueError):
            reviewer.verify(lead, cat, DAY, fetch=fake_fetch(raw, osm, []))


if __name__ == "__main__":
    unittest.main()
