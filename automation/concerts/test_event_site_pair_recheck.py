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
sys.path.insert(0, str(ROOT))
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


class ReviewedPromoterIndividualDetailTests(unittest.TestCase):
    """Reproduce the real private registry *shape* with entirely fictitious data."""

    def promoter(self):
        lead, raw, cat, osm = fixture()
        detail = (
            "https://www.livenation.fr/event/"
            "skip-the-use-synthetic-metal-show-tickets-2027")
        source = "https://www.livenation.fr/skip-the-use-tickets-adp498333"
        lead.update({
            "source": "promoter_official_tour_detail",
            "sourceUrl": detail,
            "sourcePage": source,
            "eventDetailUrl": detail,
            "sourceRole": "promoter_official",
            "artistId": "skip-the-use",
            "leadArtist": "Skip The Use",
            "name": "Skip The Use + NEW METAL SUPPORT",
        })
        raw["url"] = detail
        raw["name"] = lead["name"]
        raw["performer"][0]["name"] = "Skip The Use"
        cat["artists"] = [{
            "id": "skip-the-use", "name": "Skip The Use", "aliases": [],
        }]
        return lead, raw, cat, osm, detail, source

    @staticmethod
    def fetch(raw, osm, detail):
        def fetch(url, max_bytes):
            if url == detail:
                return ('<script type="application/ld+json">'
                        + json.dumps(raw, ensure_ascii=False)
                        + '</script>', url)
            if url == API:
                return json.dumps(osm), url
            raise AssertionError("Unreviewed URL attempted: " + str(url))
        return fetch

    def test_real_registry_detail_shape_produces_paired_approvals(self):
        lead, raw, cat, osm, detail, source = self.promoter()
        event, site = reviewer.verify(
            lead, cat, DAY, fetch=self.fetch(raw, osm, detail))
        self.assertEqual(event["event"]["officialUrl"], detail)
        self.assertEqual(event["event"]["artistIds"][0], "skip-the-use")
        self.assertEqual(site["eventBinding"]["authoritySourceUrl"], source)
        self.assertEqual(site["eventBinding"]["authorityArtistId"], "skip-the-use")
        self.assertEqual(site["eventBinding"]["eventId"], event["event"]["id"])
        before = {"schema": publisher.SCHEMA,
                  "approvals": [], "venueApprovals": []}
        private = {"items": {"promoter-example": {
            "candidate": lead, "stableObservations": 2,
            "status": "pending_review",
        }}}
        proposal, report = official_recheck.process(
            private, cat, before, DAY,
            fetch=lambda *_: self.fail("legacy event fetch used"),
            site_fetch=self.fetch(raw, osm, detail))
        self.assertEqual(report["newApprovals"], [event["event"]["id"]])
        self.assertEqual(report["newSiteApprovals"], [site["venue"]["id"]])
        # The historical reference predates the public admission of
        # skip-the-use; the real catalogue includes that artist today.
        # Validate the new event against the REAL per-row publisher using
        # exactly the current catalogue identity. The existing 7WEEKS test
        # covers the full append-only atomic preflight against the baseline.
        approved_event = proposal["approvals"][0]
        approved_site = proposal["venueApprovals"][0]
        venue = publisher.validate_venue_approval(
            approved_site, DAY, proposal["approvals"])
        concert, artists = publisher.validate_approval(
            approved_event, {venue["id"]: venue},
            {a["id"]: a for a in cat["artists"]}, DAY)
        self.assertEqual(concert["officialUrl"], detail)
        self.assertEqual(concert["venueId"], venue["id"])
        self.assertEqual(set(artists), {"new-metal-support"})
        self.assertEqual(artists["new-metal-support"]["name"],
                         "NEW METAL SUPPORT")

    def test_untrusted_detail_page_or_modified_tour_scope_is_held_pre_fetch(self):
        lead, raw, cat, osm, detail, source = self.promoter()
        mutations = (
            {"sourcePage": "https://unverified.example/tour/"},
            {"sourcePage": detail},
            {"sourceUrl": source},
            {"sourceUrl": detail + "?tracking=1"},
            {"eventDetailUrl": "https://www.livenation.fr/other/skip-the-use/"},
            {"eventDetailUrl": "https://evil.example/event/skip-the-use/"},
            {"sourceRole": "artist_official"},
            {"artistId": "someone-else"},
            {"source": "third_party_calendar_lead"},
        )
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                reviewer.verify({**lead, **change}, cat, DAY,
                    fetch=lambda *_: self.fail("Must not touch the network"))

    def test_listings_with_no_individual_page_remain_unpublishable(self):
        lead, raw, cat, osm, detail, source = self.promoter()
        lead.pop("eventDetailUrl")
        lead["source"] = "promoter_official_tour"
        lead["sourceUrl"] = source
        with self.assertRaises(ValueError):
            reviewer.verify(
                lead, cat, DAY,
                fetch=lambda *_: self.fail("Listing cannot be a proof"))
        lead["source"] = "artist_official_tour_listing"
        with self.assertRaises(ValueError):
            reviewer.verify(
                lead, cat, DAY,
                fetch=lambda *_: self.fail("Listing cannot be a proof"))


class GenericFirstPartyStructuredEventTests(unittest.TestCase):
    """Site attestation can use a full Event with genre, never genre by guess."""

    def test_generic_event_with_complete_individual_music_proof_is_publishable(self):
        lead, raw, cat, osm = fixture()
        raw["@type"] = "Event"
        calls = []
        event, site = reviewer.verify(
            lead, cat, DAY, fetch=fake_fetch(raw, osm, calls))
        self.assertEqual(calls, [EVENT, API])
        self.assertEqual(event["event"]["genres"], ["Heavy Metal"])
        self.assertEqual(site["venue"]["geoSource"], OSM)
        original = {"schema": publisher.SCHEMA,
                    "approvals": [], "venueApprovals": []}
        registry = {"items": {"fixture": {
            "candidate": lead, "status": "pending_review",
            "stableObservations": 2,
        }}}
        proposed, report = official_recheck.process(
            registry, cat, original, DAY,
            site_fetch=fake_fetch(raw, osm, []))
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(report["newSiteApprovals"]), 1)
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        validated = gate.validate_proposal(
            original, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(validated["validatedByPublisher"])
        self.assertEqual(validated["publishableEvents"], 1)

    def test_generic_event_with_venue_rock_menu_only_is_rejected(self):
        lead, raw, cat, osm = fixture()
        raw["@type"] = "Event"
        raw.pop("genre")
        with self.assertRaises(ValueError):
            reviewer.verify(lead, cat, DAY,
                            fetch=fake_fetch(raw, osm, []))
        raw["genre"] = "Rock"  # generic venue category, not a precise genre
        with self.assertRaises(ValueError):
            reviewer.verify(lead, cat, DAY,
                            fetch=fake_fetch(raw, osm, []))

    def test_mixed_event_and_musicevent_pages_cannot_lend_proofs(self):
        lead, raw, cat, osm = fixture()
        for alt in (
            {**raw, "@type": "Event", "name": "Other festival"},
            {**raw, "@type": "MusicEvent", "name": "Other show"},
        ):
            page = ('<script type="application/ld+json">'
                    + json.dumps({"@graph": [raw, alt]}, ensure_ascii=False)
                    + '</script>')
            def fetched(url, limit):
                if url == EVENT:
                    return page, EVENT
                self.fail("No geography should be requested from mixed events")
            with self.subTest(alt=alt["@type"]), self.assertRaises(ValueError):
                reviewer.verify(lead, cat, DAY, fetch=fetched)

    def test_generic_event_bad_country_or_unnamed_artist_is_rejected(self):
        lead, raw, cat, osm = fixture()
        raw["@type"] = "Event"
        for changed in (
            {"performer": [{"@type": "Organization", "name": "Guest"}]},
            {"location": {**raw["location"], "address": {
                **raw["location"]["address"], "addressCountry": "BE"}}},
            {"genre": ["Hardcore Techno"]},
            {"startDate": "2027-06-17"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                reviewer.verify(
                    lead, cat, DAY,
                    fetch=fake_fetch({**raw, **changed}, osm, []))


class IndependentBANAndNamedOSMWithoutOfficialLinkTests(unittest.TestCase):
    """Two independent remote datasets, simulated; no street centroid is signed."""

    @staticmethod
    def setup(kind="node"):
        lead, raw, cat, osm = fixture()
        raw["@type"] = "Event"
        raw["location"].pop("sameAs")
        raw["location"]["address"]["streetAddress"] = "12 Avenue des Essais"
        ban = {
            "type": "FeatureCollection",
            "features": [{"type": "Feature",
                "properties": {"postcode": "75007", "city": "Paris",
                               "street": "Avenue des Essais",
                               "housenumber": "12", "type": "housenumber",
                               "score": 0.98},
                "geometry": {"type": "Point",
                             "coordinates": [2.29401, 48.85802]},
            }],
        }
        node = ('<node id="123456789" lat="48.8580" lon="2.2940">'
                '<tag k="name" v="Esplanade des Tests"/>'
                '<tag k="addr:city" v="Paris"/>'
                '<tag k="addr:postcode" v="75007"/>'
                '<tag k="addr:street" v="Avenue des Essais"/>'
                '<tag k="addr:housenumber" v="12"/>'
                '</node>')
        if kind == "way":
            node = ('<node id="110" lat="48.85795" lon="2.29395"/>'
                    '<node id="111" lat="48.85810" lon="2.29395"/>'
                    '<node id="112" lat="48.85810" lon="2.29410"/>'
                    '<way id="456789">'
                    '<nd ref="110"/><nd ref="111"/><nd ref="112"/>'
                    '<tag k="name" v="Esplanade des Tests"/>'
                    '<tag k="addr:city" v="Paris"/>'
                    '<tag k="addr:postcode" v="75007"/>'
                    '</way>')
        return lead, raw, cat, ban, '<osm version="0.6">' + node + '</osm>'

    @staticmethod
    def fetched(raw, ban, map_data, calls):
        import independent_named_site_geo as geocoder
        def fetch(url, byte_limit):
            calls.append(url)
            if url == EVENT:
                return '<script type="application/ld+json">' + json.dumps(
                    raw, ensure_ascii=False) + '</script>', url
            if url.startswith(geocoder.BAN + "?"):
                return json.dumps(ban, ensure_ascii=False), url
            if url.startswith(geocoder.OSM_MAP + "?bbox="):
                return map_data, url
            raise AssertionError("Unexpected URL (no arbitrary candidate host): "
                                 + str(url))
        return fetch

    def test_event_without_any_osm_url_verifies_named_site_and_real_publisher(self):
        lead, raw, cat, ban, map_data = self.setup()
        calls = []
        fetch = self.fetched(raw, ban, map_data, calls)
        app, site = reviewer.verify(lead, cat, DAY, fetch=fetch)
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[1].startswith(
            "https://data.geopf.fr/geocodage/search/?q="))
        self.assertTrue(calls[2].startswith(
            "https://api.openstreetmap.org/api/0.6/map?bbox="))
        self.assertEqual(site["venue"]["geoSource"], OSM)
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-point")
        self.assertEqual(site["venue"]["latitude"], 48.858)
        self.assertNotEqual(site["venue"]["latitude"], 48.85802)
        ledger = {"schema": publisher.SCHEMA,
                  "approvals": [], "venueApprovals": []}
        registry = {"items": {"synthetic": {
            "status": "pending_review", "stableObservations": 2,
            "candidate": lead,
        }}}
        proposed, report = official_recheck.process(
            registry, cat, ledger, DAY, site_fetch=fetch)
        self.assertEqual(len(report["newSiteApprovals"]), 1)
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        validated = gate.validate_proposal(
            ledger, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(validated["validatedByPublisher"])
        self.assertEqual(validated["publishableEvents"], 1)

    def test_named_physical_area_is_not_reduced_to_a_city_centroid(self):
        lead, raw, cat, ban, map_data = self.setup("way")
        app, site = reviewer.verify(
            lead, cat, DAY, fetch=self.fetched(raw, ban, map_data, []))
        self.assertEqual(site["venue"]["geoSource"],
                         "https://www.openstreetmap.org/way/456789")
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-area")
        self.assertEqual(site["locationKind"], "named-physical-site")
        self.assertEqual(site["eventBinding"]["eventId"], app["event"]["id"])

    def test_official_named_osm_way_must_match_independent_ban_and_osm(self):
        lead, raw, cat, ban, map_data = self.setup("way")
        official_way = "https://www.openstreetmap.org/way/456789"
        raw["location"]["sameAs"] = official_way
        calls = []
        fetch = self.fetched(raw, ban, map_data, calls)
        app, site = reviewer.verify(lead, cat, DAY, fetch=fetch)
        self.assertEqual(len(calls), 3)
        self.assertEqual(site["venue"]["geoSource"], official_way)
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-area")
        self.assertEqual(site["venue"]["id"], (
            __import__("scripts.concert_event_site_contract", fromlist=["site_id"])
            .site_id(site["venue"]["name"], site["venue"]["city"],
                     official_way)))
        approvals = {"schema": publisher.SCHEMA,
                     "approvals": [], "venueApprovals": []}
        proposed, report = official_recheck.process(
            {"items": {"synthetic": {
                "candidate": lead, "stableObservations": 2,
                "status": "pending_review"}}},
            cat, approvals, DAY, site_fetch=fetch)
        self.assertEqual(len(report["newSiteApprovals"]), 1)
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        checked = gate.validate_proposal(
            approvals, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(checked["validatedByPublisher"])
        self.assertEqual(checked["publishableEvents"], 1)

    def test_private_generic_venue_preflight_reuses_same_way_proof(self):
        import dynamic_venue_evidence_preflight as preflight
        lead, raw, cat, ban, map_data = self.setup("way")
        raw["location"]["sameAs"] = (
            "https://www.openstreetmap.org/way/456789")
        page = ('<script type="application/ld+json">'
                + json.dumps(raw, ensure_ascii=False)
                + '</script>')
        _, _, _, _, site = reviewer._official_event(
            lead, page, EVENT, DAY)
        calls = []
        result = preflight._coordinates(
            site, self.fetched(raw, ban, map_data, calls))
        self.assertEqual(result[0],
                         "https://www.openstreetmap.org/way/456789")
        self.assertEqual(result[3], "named-site-area")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith(
            "https://data.geopf.fr/geocodage/search/"))
        self.assertTrue(calls[1].startswith(
            "https://api.openstreetmap.org/api/0.6/map"))

    def test_official_osm_way_cannot_disagree_with_independent_location(self):
        lead, raw, cat, ban, map_data = self.setup("way")
        for forged in (
            "https://www.openstreetmap.org/way/999999",
            "https://www.openstreetmap.org/relation/456789",
            "https://www.openstreetmap.org/way/456789?utm_source=ad",
        ):
            with self.subTest(forged=forged):
                raw["location"]["sameAs"] = forged
                calls = []
                with self.assertRaises(ValueError):
                    reviewer.verify(
                        lead, cat, DAY,
                        fetch=self.fetched(raw, ban, map_data, calls))
                if "/way/999999" in forged:
                    self.assertEqual(len(calls), 3)
                else:
                    self.assertEqual(len(calls), 1)

    def test_bad_government_address_cannot_send_a_guess_to_osm(self):
        lead, raw, cat, ban, map_data = self.setup()
        import copy as cp
        for modified in (
            {"score": 0.6},
            {"postcode": "69007"},
            {"city": "Lyon"},
            {"street": "Rue de la République"},
            {"type": "street"},
            {"housenumber": "18"},
        ):
            bad = cp.deepcopy(ban)
            bad["features"][0]["properties"].update(modified)
            calls = []
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                reviewer.verify(
                    lead, cat, DAY,
                    fetch=self.fetched(raw, bad, map_data, calls))
            self.assertEqual(len(calls), 2)
        ambiguous = cp.deepcopy(ban)
        ambiguous["features"].append(cp.deepcopy(ambiguous["features"][0]))
        with self.assertRaises(ValueError):
            reviewer.verify(
                lead, cat, DAY,
                fetch=self.fetched(raw, ambiguous, map_data, []))

    def test_wrong_osm_name_postcode_or_duplicate_stays_blocked(self):
        lead, raw, cat, ban, map_data = self.setup()
        bad_maps = (
            map_data.replace("Esplanade des Tests", "Unrelated Building"),
            map_data.replace("75007", "69000"),
            map_data.replace('v="Paris"', 'v="Lyon"'),
            map_data.replace('lon="2.2940"', 'lon="3.2940"'),
            map_data.replace("</osm>",
                '<node id="123456790" lat="48.858" lon="2.294">'
                '<tag k="name" v="Esplanade des Tests"/>'
                '<tag k="addr:city" v="Paris"/>'
                '<tag k="addr:postcode" v="75007"/></node></osm>'),
        )
        for bad in bad_maps:
            with self.subTest(map=bad[:70]), self.assertRaises(ValueError):
                reviewer.verify(lead, cat, DAY,
                    fetch=self.fetched(raw, ban, bad, []))

    def test_official_venue_website_link_does_not_become_geo_authority(self):
        lead, raw, cat, ban, map_data = self.setup()
        raw["location"]["url"] = "https://venue.example/infos-pratiques"
        calls = []
        reviewer.verify(lead, cat, DAY,
                        fetch=self.fetched(raw, ban, map_data, calls))
        self.assertEqual(len(calls), 3)
        self.assertFalse(any("venue.example" in call for call in calls))

    def test_empty_or_ambiguous_geography_fails_closed(self):
        lead, raw, cat, ban, map_data = self.setup()
        bad = dict(ban, features=[])
        with self.assertRaises(ValueError):
            reviewer.verify(
                lead, cat, DAY,
                fetch=self.fetched(raw, bad, map_data, []))
        raw["location"]["address"]["addressCountry"] = "BE"
        calls = []
        with self.assertRaises(ValueError):
            reviewer.verify(
                lead, cat, DAY,
                fetch=self.fetched(raw, ban, map_data, calls))
        # Reading the first-party event is necessary to detect its country.
        # A falsified country MUST never reach external geography services.
        self.assertEqual(calls, [EVENT])


if __name__ == "__main__":
    unittest.main()
