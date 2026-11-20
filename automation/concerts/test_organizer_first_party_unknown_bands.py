"""No artist allowlist: a trusted organizer can debut an entirely new bill.

All concert names, geography and proof payloads are synthetic. The organizer
source is a reviewed first-party authority, never a band or venue allowlist.
The publisher must independently verify official identity and OSM site.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import concerts_cloud_sync as publisher
import approval_preflight as preflight
import event_site_pair_recheck as reviewer
import official_recheck
import organizer_source_contract as source_contract

DAY = dt.date(2026, 11, 20)
EVENT_DAY = "2027-05-17"
SOURCE = "https://slhproductions.fr/agenda/"
EVENT_URL = SOURCE + "synthetic-black-metal-debut-2027/"
ARTISTS = ["UNHEARD BLACK METAL", "DEBUT DOOM PUNK", "NEW THRASH ACT"]
OSM = "https://www.openstreetmap.org/node/123456789"
API = "https://api.openstreetmap.org/api/0.6/node/123456789.json"


def fixture():
    candidate = {
        "candidateId": "synthetic-organizer-first-ever-show",
        "source": "organizer_official_event_detail",
        "sourceRole": "organizer_official",
        "organizerSourceId": "sounds-like-hell-productions",
        "sourcePage": SOURCE,
        "sourceUrl": EVENT_URL,
        "eventDetailUrl": EVENT_URL,
        "date": EVENT_DAY,
        "name": " + ".join(ARTISTS),
        "leadArtist": ARTISTS[0],
        "venue": "Esplanade des Tests",
        "city": "Paris",
        "department": "75",
        "classification": ["Black Metal", "Doom"],
        "reviewBucket": "genre_tag_review",
        "newVenueToReview": True,
        "possibleExistingConcert": False,
        "publicationAllowed": False,
        "reviewRequired": True,
    }
    event = {
        "@type": "MusicEvent", "url": EVENT_URL,
        "name": candidate["name"],
        "startDate": EVENT_DAY + "T20:00:00+02:00",
        "genre": ["Black Metal", "Doom"],
        "performer": [{"@type": "MusicGroup", "name": x}
                      for x in ARTISTS],
        "location": {"@type": "Place",
                     "name": candidate["venue"], "sameAs": OSM,
                     "address": {"@type": "PostalAddress",
                                 "streetAddress": "Avenue des Essais",
                                 "postalCode": "75007",
                                 "addressLocality": "Paris",
                                 "addressRegion": "Île-de-France",
                                 "addressCountry": "FR"}},
    }
    catalogue = {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "artists": [], "venues": [], "events": [],
    }
    osm = {"version": "0.6", "elements": [{
        "id": 123456789, "type": "node",
        "lat": 48.858, "lon": 2.294,
        "tags": {"name": "Esplanade des Tests", "addr:city": "Paris",
                 "addr:postcode": "75007", "addr:country": "FR"},
    }]}
    return candidate, event, catalogue, osm


def fetch(event, osm, calls):
    def get(url, max_bytes):
        calls.append(url)
        if url == EVENT_URL:
            return ('<script type="application/ld+json">'
                    + json.dumps(event, ensure_ascii=False)
                    + '</script>'), url
        if url == API:
            return json.dumps(osm), url
        raise AssertionError("Unexpected network authority or site: " + str(url))
    return get


class OrganizerWithoutAnyKnownBandTests(unittest.TestCase):
    def test_first_ever_unknown_bands_and_new_venue_reach_real_publisher(self):
        lead, raw, catalogue, osm = fixture()
        calls = []
        event, site = reviewer.verify(lead, catalogue, DAY,
                                      fetch=fetch(raw, osm, calls))
        self.assertEqual(calls, [EVENT_URL, API])
        self.assertEqual(len(event["newArtists"]), 3)
        self.assertEqual(event["event"]["artistIds"],
                         ["unheard-black-metal", "debut-doom-punk", "new-thrash-act"])
        self.assertEqual(site["eventBinding"]["authorityArtistId"], None)
        self.assertEqual(site["eventBinding"]["authoritySourceUrl"], SOURCE)
        self.assertEqual(site["venue"]["geoSource"], OSM)

        previous = {"schema": publisher.SCHEMA,
                    "approvals": [], "venueApprovals": []}
        registry = {"items": {"first-ever": {
            "status": "pending_review", "stableObservations": 2,
            "candidate": lead,
        }}}
        proposed, report = official_recheck.process(
            registry, catalogue, previous, DAY,
            site_fetch=fetch(raw, osm, []),
            fetch=lambda *_: self.fail("Unsafe legacy fetch"))
        self.assertEqual(report["newApprovals"],
                         [event["event"]["id"]])
        self.assertEqual(report["newSiteApprovals"],
                         [site["venue"]["id"]])
        self.assertEqual(previous["approvals"], [])
        self.assertEqual(previous["venueApprovals"], [])
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        checked = preflight.validate_proposal(
            previous, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(checked["validatedByPublisher"])
        self.assertEqual(checked["publishableEvents"], 1)

    def test_missing_first_party_region_needs_exact_government_postal_attestation(self):
        lead, raw, catalogue, osm = fixture()
        raw["location"]["address"].pop("addressRegion")
        gov_url = "https://data.geopf.fr/geocodage/search/"
        calls = []

        def verified_fetch(url, cap):
            calls.append(url)
            if url.startswith(gov_url + "?"):
                return json.dumps({"features": [{
                    "type": "Feature",
                    "properties": {
                        "postcode": "75007", "city": "Paris",
                        "street": "Avenue des Essais",
                        "type": "street", "score": 0.97,
                        "context": "75, Paris, Île-de-France"},
                    "geometry": {"type": "Point",
                                 "coordinates": [2.294, 48.858]},
                }]}), url
            return fetch(raw, osm, [])(url, cap)

        event, site = reviewer.verify(lead, catalogue, DAY,
                                      fetch=verified_fetch)
        self.assertEqual(site["venue"]["region"], "Île-de-France")
        self.assertTrue(any(u.startswith(gov_url + "?") for u in calls))
        self.assertEqual(site["venue"]["geoSource"], OSM)
        self.assertEqual(len(event["newArtists"]), 3)

        # Exact government address but WRONG department is not admissible.
        def wrong_ban(url, cap):
            if url.startswith(gov_url + "?"):
                return json.dumps({"features": [{
                    "properties": {"postcode": "75007", "city": "Paris",
                                   "street": "Avenue des Essais",
                                   "type": "street", "score": 0.97,
                                   "context": "93, Seine-Saint-Denis, Île-de-France"},
                    "geometry": {"type": "Point",
                                 "coordinates": [2.294, 48.858]},
                }]}), url
            return fetch(raw, osm, [])(url, cap)
        with self.assertRaises(ValueError):
            reviewer.verify(lead, catalogue, DAY, fetch=wrong_ban)

        # An official no-region event without government support stays held.
        def unavailable_ban(url, cap):
            if url.startswith(gov_url + "?"):
                raise ValueError("Government address verification unavailable")
            return fetch(raw, osm, [])(url, cap)
        with self.assertRaises(ValueError):
            reviewer.verify(lead, catalogue, DAY, fetch=unavailable_ban)

    def test_independent_recheck_accepts_only_named_performer_genre_in_same_event(self):
        lead, raw, catalogue, osm = fixture()
        raw.pop("genre")
        for band in raw["performer"]:
            band["genre"] = ("Black Metal" if band["name"] == ARTISTS[0]
                             else "Jazz")
        event, site = reviewer.verify(lead, catalogue, DAY,
                                      fetch=fetch(raw, osm, []))
        self.assertIn("Black Metal", event["event"]["genres"])
        self.assertEqual(len(event["newArtists"]), 3)
        self.assertEqual(site["venue"]["geoSource"], OSM)

        for bad in ("Hardcore Techno", "Jazz"):
            altered = copy.deepcopy(raw)
            for band in altered["performer"]:
                band["genre"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                reviewer.verify(lead, catalogue, DAY,
                                fetch=fetch(altered, osm, []))

        # No performer-level genre may override a contradictory explicit
        # unrelated event-level genre, and no artist biography is consulted.
        altered = copy.deepcopy(raw)
        altered["genre"] = ["Jazz"]
        with self.assertRaises(ValueError):
            reviewer.verify(lead, catalogue, DAY,
                            fetch=fetch(altered, osm, []))

    def test_no_source_lead_can_invent_a_reviewed_organizer(self):
        lead, event, catalogue, osm = fixture()
        for update in (
            {"sourcePage": "https://untrusted.example/agenda/"},
            {"sourceUrl": "https://untrusted.example/agenda/new-show/"},
            {"eventDetailUrl": "https://untrusted.example/show/"},
            {"sourceRole": "promoter_official"},
            {"organizerSourceId": "invented-source"},
            {"artistId": "unheard-black-metal"},
            {"newVenueToReview": False},
            {"publicationAllowed": True},
            {"possibleExistingConcert": True},
            {"reviewBucket": "festival_overlap_review"},
            {"eventDetailUrl": SOURCE + "some/fake/nested/show/"},
            {"eventDetailUrl": SOURCE + "show/?ref=tracking"},
        ):
            with self.subTest(update=update):
                with self.assertRaises(ValueError):
                    reviewer.verify({**lead, **update}, catalogue, DAY,
                                    fetch=lambda *_: self.fail(
                                        "No network for an unreviewed authority"))

    def test_artist_identity_and_genre_are_still_event_specific(self):
        lead, raw, catalogue, osm = fixture()
        wrong = (
            {**raw, "genre": ["Jazz"]},
            {**raw, "genre": ["Hardcore Techno"]},
            {**raw, "performer": [{"@type": "MusicGroup", "name": "OTHER"}]},
            {**raw, "startDate": "2027-05-18"},
            {**raw, "eventStatus": "https://schema.org/EventCancelled"},
            {**raw, "location": {**raw["location"], "name": "Wrong Square"}},
        )
        for alt in wrong:
            with self.subTest(field=alt.keys()):
                calls = []
                with self.assertRaises(ValueError):
                    reviewer.verify(lead, catalogue, DAY,
                                    fetch=fetch(alt, osm, calls))
                self.assertEqual(calls, [EVENT_URL])

    def test_publisher_rejects_forged_organizer_binding(self):
        lead, raw, catalogue, osm = fixture()
        approved_event, approved_site = reviewer.verify(
            lead, catalogue, DAY, fetch=fetch(raw, osm, []))
        for change in (
            {"authoritySourceUrl": "https://untrusted.example/agenda/"},
            {"authoritySourceUrl": EVENT_URL},
            {"authorityArtistId": "unheard-black-metal"},
            {"eventOfficialUrl": "https://slhproductions.fr/agenda/other-event/"},
        ):
            with self.subTest(change=change):
                bad = copy.deepcopy(approved_site)
                bad["eventBinding"].update(change)
                with self.assertRaises(ValueError):
                    publisher.validate_venue_approval(
                        bad, DAY, [approved_event])

    def test_manifest_requires_exact_reviewed_scope(self):
        rows = source_contract.read_sources()
        self.assertTrue(rows)
        spec = next(x for x in rows if x["id"] ==
                    "sounds-like-hell-productions")
        self.assertTrue(source_contract.scoped_event_url(spec, EVENT_URL))
        for bad in (
            SOURCE,
            SOURCE + "a/b/",
            SOURCE + "valid-show/?tracking=1",
            "http://slhproductions.fr/agenda/valid-show/",
            "https://other.example/agenda/valid-show/",
            "https://slhproductions.fr.evil.example/agenda/valid-show/",
            "https://slhproductions.fr/agenda/../valid-show/",
            "https://slhproductions.fr/agenda/valid-show/#ref",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(source_contract.scoped_event_url(spec, bad))

    def test_rogue_manifest_cannot_create_an_artist_or_organizer_authority(self):
        verified = source_contract.read_sources()
        manifest = json.loads(source_contract.MANIFEST.read_text(
            encoding="utf-8"))
        for edit in (
            {"host": "evil.example"},
            {"url": "https://evil.example/agenda/"},
            {"eventPathPrefix": "/"},
            {"officialEvidenceUrl": "https://other.example/about/"},
            {"id": verified[0]["id"] + "?"}
        ):
            modified = copy.deepcopy(manifest)
            modified["sources"][0].update(edit)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "sources.json"
                path.write_text(json.dumps(modified), encoding="utf-8")
                with self.subTest(edit=edit), self.assertRaises(ValueError):
                    source_contract.read_sources(path)


if __name__ == "__main__":
    unittest.main()
