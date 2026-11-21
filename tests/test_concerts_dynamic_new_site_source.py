"""Synthetic offline proofs for an UNKNOWN first-party concert origin and NEW site.

A passing test is NOT publication: these tests exercise only independent
live evidence. The Publisher remains a separate mandatory contract.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest

from automation.concerts import event_site_pair_recheck as sites
from scripts import concert_event_site_contract as site_contract
from scripts import concert_dynamic_new_site_source as checker

TODAY = dt.date(2026, 11, 21)
DAY = "2027-05-13"
ORIGIN_OSM = "https://www.openstreetmap.org/node/812345671"
ORIGIN_API = "https://api.openstreetmap.org/api/0.6/node/812345671"
SITE_OSM = "https://www.openstreetmap.org/node/912345678"
SITE_API = "https://api.openstreetmap.org/api/0.6/node/912345678.json"
ORIGIN_HOME = "https://scene-officielle-inconnue.fr/"
EVENT_URL = "https://scene-officielle-inconnue.fr/concert/2027-nuit-metal/"
WITNESS_URL = "https://agenda-independant.fr/evenements/2027-nuit-metal/"
BANDS = [f"Groupe Nouvelle Vague {i}" for i in range(1, 9)]


def fixture():
    known_venue = {
        "id": "le-signal",
        "name": "Le Signal", "city": "Lyon",
        "postalCode": "69007", "department": "69",
        "address": "15 rue Inventée", "region": "Auvergne-Rhône-Alpes",
        "latitude": 45.757, "longitude": 4.831,
        "geoSource": ORIGIN_OSM,
    }
    site = {
        "name": "Place Libre", "city": "Tours",
        "address": "Place Libre", "postalCode": "37000",
        "department": "37", "region": "Centre-Val de Loire",
        "latitude": 47.395, "longitude": 0.688,
        "geoSource": SITE_OSM, "geoPrecision": "named-site-point",
    }
    site["id"] = site_contract.site_id(
        site["name"],site["city"],site["geoSource"])
    artists, fresh = sites._artists(BANDS, {"artists": []})
    event = {
        "id": "go-c-20270513-tours-groupe-nouvelle-vague-1",
        "title": " + ".join(BANDS), "date": DAY, "time": None,
        "officialUrl": EVENT_URL, "artistIds": artists,
        "venueId": site["id"], "genres": ["Death Metal"],
        "status": "confirmed", "sourceType": "organisateur",
    }
    event_review = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "event": event, "newArtists": fresh,
        "officialEvidence": [{
            "url": EVENT_URL, "proofType": "official-organizer-or-venue",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
        }, {
            "url": EVENT_URL, "proofType": checker.PROFILE,
            "checkedAt": TODAY.isoformat(),
            "checkedFields": list(checker.CHECKED),
            "originVenueId": known_venue["id"],
            "originVenueOsmUrl": ORIGIN_OSM,
            "corroboratingEventUrl": WITNESS_URL,
            "officialArtistNames": BANDS,
            "officialGenreLabels": ["Death Metal"],
        }],
    }
    site_review = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "venueKind": "independent-event-site-v1",
        "locationKind": "named-physical-site",
        "venue": site,
        "eventBinding": {
            "eventId": event["id"], "eventDate": DAY,
            "eventOfficialUrl": EVENT_URL,
            "authoritySourceUrl": ORIGIN_HOME,
            "authorityArtistId": None,
        },
        "officialEvidence": [{
            "url": EVENT_URL, "proofType": "official-event-location",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": [
                "eventId", "date", "venueName", "city", "country"],
            "eventId": event["id"], "venueName": site["name"],
            "city": site["city"], "country": "FR",
        }, {
            "url": SITE_OSM, "proofType": "independent-osm-site",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": [
                "venueName", "city", "coordinates", "country"],
            "venueName": site["name"], "city": site["city"],
            "country": "FR", "latitude": site["latitude"],
            "longitude": site["longitude"],
            "geoPrecision": site["geoPrecision"],
        }],
    }
    raw = {
        "@type": "MusicEvent",
        "url": EVENT_URL, "name": " + ".join(BANDS),
        "startDate": DAY + "T21:00:00+02:00",
        "genre": ["Death Metal"],
        "performer": [
            {"@type": "MusicGroup", "name": n} for n in BANDS],
        "location": {
            "@type": "Place", "name": site["name"],
            "sameAs": SITE_OSM,
            "address": {
                "@type": "PostalAddress",
                "addressLocality": site["city"],
                "postalCode": site["postalCode"],
                "streetAddress": site["address"],
                "addressRegion": site["region"],
                "addressCountry": "FR",
            },
        },
    }
    witness = {
        "@type": "MusicEvent", "name": raw["name"],
        "url": WITNESS_URL,
        "startDate": DAY + "T21:00:00+02:00",
        "genre": ["Death Metal"],
        "performer": [{"@type": "MusicGroup", "name": BANDS[0]}],
        "location": copy.deepcopy(raw["location"]),
    }
    witness["location"].pop("sameAs", None)
    node = {
        "version": "0.6", "elements": [{
            "id": 912345678, "type": "node",
            "lat": 47.395, "lon": 0.688,
            "tags": {
                "name": site["name"], "addr:city": site["city"],
                "addr:postcode": "37000", "addr:country": "FR",
            },
        }],
    }
    origin = (
        '<osm version="0.6"><node id="812345671" '
        'lat="45.757" lon="4.831">'
        '<tag k="name" v="Le Signal"/>'
        '<tag k="addr:city" v="Lyon"/>'
        '<tag k="addr:postcode" v="69007"/>'
        '<tag k="addr:country" v="FR"/>'
        '<tag k="website" v="' + ORIGIN_HOME + '"/>'
        '</node></osm>'
    )
    return event_review, site_review, known_venue, raw, witness, node, origin


def read(review=None, site_review=None, venue=None,
         raw=None, witness=None, node=None, origin=None):
    base = fixture()
    review = copy.deepcopy(review if review is not None else base[0])
    site_review = copy.deepcopy(site_review if site_review is not None else base[1])
    venue = copy.deepcopy(venue if venue is not None else base[2])
    raw = copy.deepcopy(raw if raw is not None else base[3])
    witness = copy.deepcopy(witness if witness is not None else base[4])
    node = copy.deepcopy(node if node is not None else base[5])
    origin = origin if origin is not None else base[6]
    pages = {
        ORIGIN_API: origin,
        EVENT_URL: ('<html><script type="application/ld+json">'
                    + json.dumps(raw) + '</script></html>'),
        SITE_API: json.dumps(node),
        WITNESS_URL: ('<html><script type="application/ld+json">'
                      + json.dumps(witness) + '</script></html>'),
    }
    calls = []
    def fetch(url, cache):
        calls.append(url)
        if url not in pages:
            raise AssertionError("Unexpected internet request: " + url)
        return pages[url]
    return checker.verify(
        review, site_review, {venue["id"]: venue}, {}, TODAY,
        fetch=fetch), calls


class OpenOriginNewSiteProofTests(unittest.TestCase):
    def test_eight_new_bands_offsite_named_osm_and_second_domain(self):
        ok, calls = read()
        self.assertTrue(ok)
        self.assertEqual(calls,
                         [ORIGIN_API, EVENT_URL, SITE_API, WITNESS_URL])
        # Evidence validation is NOT an admission, publisher mutation,
        # or signed private ledger write.

    def test_live_proof_alone_cannot_bypass_the_existing_publisher_gate(self):
        review, location, *_ = fixture()
        # This new verifier deliberately cannot register an event site:
        # the real Publisher still needs an explicit integrated contract.
        with self.assertRaises(ValueError):
            site_contract.validate(location, TODAY, [review])

    def test_no_first_party_domain_ownership_cannot_pass(self):
        review, location, origin_venue, raw, witness, node, origin = fixture()
        cases = [
            origin.replace(ORIGIN_HOME, "https://fraudulent-origin.fr/"),
            origin.replace('k="name" v="Le Signal"',
                           'k="name" v="Le Signal Inconnu"'),
            origin.replace('lat="45.757"', 'lat="49.000"'),
            origin.replace('k="addr:postcode" v="69007"',
                           'k="addr:postcode" v="31000"'),
        ]
        for bad in cases:
            with self.subTest(osm=bad), self.assertRaises(ValueError):
                read(origin=bad)

    def test_no_forged_witness_or_cross_domain_reuse(self):
        review, location, venue, raw, witness, node, origin = fixture()
        modifications = [
            {"date": "2027-05-14"},
            {"location": {
                "@type": "Place", "name": "Autre Endroit",
                "address": {"addressLocality": "Tours",
                            "addressCountry": "FR"}}},
            {"performer": [{"@type": "MusicGroup", "name": "Autre Groupe"}]},
            {"eventStatus": "https://schema.org/EventCancelled"},
        ]
        for bad in modifications:
            with self.subTest(witness=bad), self.assertRaises(ValueError):
                read(witness={**witness, **bad})
        review["officialEvidence"][1]["corroboratingEventUrl"] = EVENT_URL
        with self.assertRaises(ValueError):
            read(review=review)

    def test_first_party_altered_bill_festival_or_genre_cannot_pass(self):
        review, location, venue, raw, witness, node, origin = fixture()
        cases = [
            {**raw, "performer": raw["performer"][:-1]},
            {**raw, "genre": ["Hardcore Techno"]},
            {**raw, "name": "Festival des Sons"},
            {**raw, "eventStatus": "https://schema.org/EventPostponed"},
            {**raw, "startDate": "2027-05-14T21:00:00+02:00"},
        ]
        for bad in cases:
            with self.subTest(bad=bad["name"]), self.assertRaises(ValueError):
                read(raw=bad)

    def test_independent_osm_site_coordinates_cannot_change(self):
        review, location, venue, raw, witness, node, origin = fixture()
        for change in (
            {"lat": 48.000},
            {"tags": {**node["elements"][0]["tags"],
                      "name": "Not Place Libre"}},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                modified = copy.deepcopy(node)
                modified["elements"][0].update(change)
                read(node=modified)

    def test_unknown_source_claim_and_unapproved_site_are_not_authority(self):
        review, location, venue, raw, witness, node, origin = fixture()
        cases = [
            lambda r, s: r["officialEvidence"][1].update(
                {"originVenueId": "invented-venue-id"}),
            lambda r, s: s["eventBinding"].update(
                {"authorityArtistId": "new-synthetic-artist"}),
            lambda r, s: s.update({"reviewDecision": "pending_review"}),
            lambda r, s: r.update({"reviewedBy": "automated-untrusted-claim"}),
        ]
        for change in cases:
            altered, changed_site = copy.deepcopy(review),copy.deepcopy(location)
            change(altered, changed_site)
            with self.subTest(change=change), self.assertRaises(ValueError):
                read(review=altered,site_review=changed_site)


if __name__ == "__main__":
    unittest.main()
