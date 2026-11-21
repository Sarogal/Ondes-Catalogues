"""Synthetic full Publisher regression for unlisted concert AND unlisted venue.

No external network, hard-coded site/artist allowlist or trusted discovery
label is used. A named OSM feature alone is not enough: official exact dated
music bill, BAN address, OSM site website, and atomic Publisher approval bind.
"""
import copy
import datetime as dt
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from automation.concerts import dynamic_self_attributed_new_site_proposals as producer
from automation.concerts import approval_preflight
from scripts import concerts_cloud_sync as publisher
from scripts import concert_dynamic_new_site_source as signer
import test_concerts_dynamic_new_site_source as fixture
import test_concerts_dynamic_existing_venue as existing

TODAY = dt.date(2026, 11, 21)
URL = fixture.EVENT_URL
OSM_NODE_ID = "912345678"
OSM_URL = fixture.SITE_OSM
HOME = fixture.ORIGIN_HOME


def test_catalogue():
    return copy.deepcopy(existing.BASE)


def lead(*, name=None, venue="Place Libre", url=URL, observations=3):
    _, site_approval, _, raw, _, _, _ = fixture.fixture()
    candidate = {
        "candidateId": "venue:brand-new-2027-concert-unknown-physical-place",
        "source": "agenda_officiel_structuré",
        "sourcePage": url,
        "sourceUrl": url,
        "eventDetailUrl": url,
        "date": fixture.DAY,
        "name": name or raw["name"],
        "leadArtist": fixture.BANDS[0],
        "venue": venue, "city": "Tours", "department": "37",
        "reviewBucket": "genre_unknown",
        "publicationAllowed": False,
        "reviewRequired": True,
        "possibleExistingConcert": False,
    }
    return {
        "schema": "grossesondes.concert.intake.v1",
        "items": {"synthetic": {
            "status": "pending_review",
            "stableObservations": observations,
            "candidate": candidate,
        }},
    }


def ban(*, score=0.81, city="Tours", street="Place Libre"):
    return json.dumps({"features": [{
        "geometry": {"type": "Point", "coordinates": [0.688, 47.395]},
        "properties": {
            "postcode": "37000", "city": city, "street": street,
            "type": "street", "score": score,
            "context": "37, Indre-et-Loire, Centre-Val de Loire",
        },
    }]})


def osm_xml(*, website=HOME, name="Place Libre",
            city="Tours", lat="47.395", two=False):
    unit = (
        '<node id="' + OSM_NODE_ID + '" lat="' + lat + '" lon="0.688">'
        '<tag k="name" v="' + name + '"/>'
        '<tag k="addr:city" v="' + city + '"/>'
        '<tag k="addr:postcode" v="37000"/>'
        '<tag k="addr:country" v="FR"/>'
        '<tag k="website" v="' + website + '"/>'
        '</node>')
    duplicate = unit.replace(OSM_NODE_ID, "912345679") if two else ""
    return '<osm version="0.6">' + unit + duplicate + '</osm>'


def fetch_for(*, government=None, osm=None, raw=None, page=None,
              editing_unavailable=False):
    _, _, _, original, _, geo_node, _ = fixture.fixture()
    geo = copy.deepcopy(geo_node)
    if raw is not None:
        original = raw
    seen = []
    pages = {
        URL: (page if page is not None else
              '<html><main><h1>Concert officiel</h1>' +
              '<script type="application/ld+json">' +
              json.dumps(original, ensure_ascii=False) +
              '</script><p>Programme de la soirée</p></main></html>'),
        fixture.SITE_API: json.dumps(geo),
        "https://api.openstreetmap.org/api/0.6/node/" + OSM_NODE_ID: (
            osm if osm is not None else osm_xml()),
    }
    def get(url, cache):
        seen.append(url)
        if url.startswith("https://data.geopf.fr/geocodage/search/"):
            return government if government is not None else ban()
        if url.startswith("https://overpass.private.coffee/api/interpreter?"):
            q = parse_qs(urlsplit(url).query).get("data", [""])[0]
            if "[out:json]" in q and "node(912345678)" in q:
                return json.dumps(geo)
            if "[out:xml]" in q:
                return osm if osm is not None else osm_xml()
            raise AssertionError("Invalid read-only OSM request")
        if url.startswith("https://api.openstreetmap.org/api/0.6/map?bbox="):
            if editing_unavailable:
                raise ValueError("OSM editing API unavailable")
            return osm if osm is not None else osm_xml()
        if url in pages:
            if editing_unavailable and "api.openstreetmap.org" in url:
                raise ValueError("OSM editing API unavailable")
            return pages[url]
        raise AssertionError("Unexpected public network origin: " + url)
    return get, seen


def before():
    return {"schema": publisher.SCHEMA, "approvals": [],
            "venueApprovals": []}


class IndependentUnknownVenuePublisherTests(unittest.TestCase):
    def setUp(self):
        self.original_geo = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            existing.VENUE_ID, None)
        self.assertIsNotNone(self.original_geo)
        self.addCleanup(
            lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
                existing.VENUE_ID, self.original_geo))

    def test_eight_unknown_bands_and_unknown_room_publish_as_one_pair(self):
        base = test_catalogue()
        pending = before()
        fetch, seen = fetch_for()
        result, metrics = producer.build(lead(), base, pending, TODAY,
                                         fetch=fetch)
        self.assertEqual(metrics["eligibleUnknownSites"], 1)
        self.assertEqual(metrics["stateCounts"],
                         {"publisher_bound_event_site_pair": 1}, metrics)
        self.assertEqual(len(result["approvals"]), 1)
        self.assertEqual(len(result["venueApprovals"]), 1)
        evt, room = result["approvals"][0], result["venueApprovals"][0]
        self.assertEqual(evt["officialEvidence"][1]["proofType"],
                         signer.SELF_PROFILE)
        self.assertEqual(len(evt["newArtists"]), 8)
        self.assertEqual(evt["event"]["venueId"], room["venue"]["id"])
        self.assertEqual(room["venue"]["geoSource"], OSM_URL)
        self.assertEqual(room["eventBinding"]["authoritySourceUrl"], HOME)
        self.assertEqual(pending, before())
        self.assertTrue(any("data.geopf.fr" in x for x in seen))
        self.assertTrue(any("openstreetmap.org" in x for x in seen))

        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                pending, result, TODAY)), 1)
            published, stats = publisher.merge(
                base, base, result, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats.get("held"))
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertEqual(published["venues"][-1]["id"],
                         room["venue"]["id"])

    def test_new_room_and_eight_new_bands_reach_publisher_when_osm_editing_api_fails(self):
        # This covers the actual public runner failure: direct OSM editing API
        # is unavailable. Never skip independent identity; use a safe bounded
        # Overpass read-only geometry and exact OSM website instead.
        base = test_catalogue()
        fetch, seen = fetch_for(editing_unavailable=True)
        approvals, review = producer.build(
            lead(), base, before(), TODAY, fetch=fetch)
        self.assertEqual(review["stateCounts"],
                         {"publisher_bound_event_site_pair": 1}, review)
        self.assertTrue(any("overpass.private.coffee" in x for x in seen))
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            published, summary = publisher.merge(
                base, base, approvals, TODAY)
        self.assertEqual(summary["newEvents"], 1, summary.get("held"))
        self.assertEqual(summary["newVenues"], 1)
        self.assertEqual(summary["newArtists"], 8)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)

    def test_overpass_bad_geography_cannot_override_official_site(self):
        fake = osm_xml(website="https://impostor.invalid")
        fetch, _ = fetch_for(osm=fake, editing_unavailable=True)
        proposed, report = producer.build(
            lead(), test_catalogue(), before(), TODAY, fetch=fetch)
        self.assertEqual(proposed, before())
        self.assertEqual(report["stateCounts"],
                         {"held_source_or_site_unverified": 1})

    def test_mismatched_first_party_genre_geo_and_domain_never_propose(self):
        _, _, _, original, _, _, _ = fixture.fixture()
        cancelled = copy.deepcopy(original)
        cancelled["eventStatus"] = "https://schema.org/EventCancelled"
        no_genre = copy.deepcopy(original)
        no_genre.pop("genre", None)
        wrong_venue = copy.deepcopy(original)
        wrong_venue["location"]["name"] = "A Different Hall"
        cases = (
            ("unconfirmed_genre", {"raw": no_genre}),
            ("cancelled", {"raw": cancelled}),
            ("wrong_venue", {"raw": wrong_venue}),
            ("government_low_score", {"government": ban(score=0.70)}),
            ("wrong_government_city", {"government": ban(city="Orléans")}),
            ("forged_osm_site", {"osm": osm_xml(name="Other Hall")}),
            ("forged_event_host", {"osm": osm_xml(
                website="https://fake-venue.invalid")}),
            ("wrong_osm_coords", {"osm": osm_xml(lat="45.0")}),
            ("duplicate_map_sites", {"osm": osm_xml(two=True)}),
        )
        for label, props in cases:
            with self.subTest(label=label):
                get, _ = fetch_for(**props)
                result, report = producer.build(
                    lead(), test_catalogue(), before(), TODAY, fetch=get)
                self.assertEqual(result, before(), report)
                self.assertEqual(report["stateCounts"],
                                 {"held_source_or_site_unverified": 1}, report)

    def test_already_known_sites_and_unstable_source_are_quarantined(self):
        no_stability, _ = producer.build(
            lead(observations=1), test_catalogue(), before(),
            TODAY, fetch=lambda *_: self.fail("not eligible"))
        self.assertEqual(no_stability, before())
        already = test_catalogue()
        _, site_review, *_ = fixture.fixture()
        already["venues"].append(site_review["venue"])
        result, report = producer.build(
            lead(), already, before(), TODAY,
            fetch=lambda *_: self.fail("already published venue"))
        self.assertEqual(report["eligibleUnknownSites"], 0)
        self.assertEqual(result, before())


if __name__ == "__main__":
    unittest.main()
