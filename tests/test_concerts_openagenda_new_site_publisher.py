"""Real Publisher regression: one official OpenAgenda event + a NEW named site.

The discovery cannot self-approve. Every event/agenda UID is freshly fetched;
the location comes from independent French BAN plus a named OSM feature.
This test must make both the private preflight and production merge pass.
"""
import copy
import datetime as dt
import json
import unittest
from unittest import mock

from automation.concerts import approval_preflight
from automation.concerts import openagenda_new_site_proposals as producer
from automation.concerts import openagenda_official_concert as oa
from scripts import concert_dynamic_new_site_source as signer
from scripts import concerts_cloud_sync as publisher
import test_concerts_dynamic_new_site_source as fixture
import test_concerts_self_attributed_unknown_venue as geo_fixture
import test_concerts_dynamic_existing_venue as existing

TODAY = dt.date(2026, 11, 22)
DAY = fixture.DAY
URL = "https://openagenda.com/shotgun/events/eight-unknown-metal-bands"
AGENDA_UID, EVENT_UID = "9969608", "87654321"
OFFICIAL_EXPORT = oa.official_export_url(AGENDA_UID, EVENT_UID)


def observation(**changes):
    item = {
        "candidateId": "oa:synthetic-new-venue",
        "source": "agenda_officiel_openagenda",
        "sourceUrl": URL, "sourcePage": URL,
        "eventDetailUrl": URL,
        "openAgendaUid": AGENDA_UID, "openAgendaEventUid": EVENT_UID,
        "date": DAY, "name": " + ".join(fixture.BANDS),
        "leadArtist": fixture.BANDS[0],
        "venue": "Place Libre", "city": "Tours",
        "reviewBucket": "genre_tag_review",
        "publicationAllowed": False, "reviewRequired": True,
        "possibleExistingConcert": False,
    }
    item.update(changes)
    return {
        "schema": "grossesondes.concert.intake.v1",
        "items": {"new": {
            "status": "pending_review", "stableObservations": 1,
            "candidate": item,
        }},
    }


def official(**changes):
    record = {
        "uid": 87654321, "slug": "eight-unknown-metal-bands",
        "origin": {"uid": 9969608, "slug": "shotgun"},
        "status": 1, "firstDate": DAY, "lastDate": DAY,
        "title": {"fr": " + ".join(fixture.BANDS)},
        "keywords": {"fr": ["Death Metal", "punk"]},
        "location": {
            "name": "Place Libre", "city": "Tours",
            "address": "Place Libre, 37000 Tours, France",
            "postalCode": "37000", "countryCode": "fr",
            "latitude": 47.395, "longitude": 0.688,
        },
    }
    record.update(changes)
    return json.dumps({"total": 1, "events": [record]}, ensure_ascii=False)


def official_get(*, changes=None, gov=None, osm=None):
    geo_get, geo_seen = geo_fixture.fetch_for(government=gov, osm=osm)
    body = official(**(changes or {}))
    reads = []
    def fetch(url, cache):
        reads.append(url)
        if url == OFFICIAL_EXPORT:
            return body
        return geo_get(url, cache)
    return fetch, reads


class OpenAgendaNewNamedSitePublisherTests(unittest.TestCase):
    def setUp(self):
        original = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            existing.VENUE_ID, None)
        self.assertIsNotNone(original)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            existing.VENUE_ID, original))

    def test_new_room_and_eight_unknown_artists_publish_atomically(self):
        base = geo_fixture.test_catalogue()
        previous = geo_fixture.before()
        fetch, reads = official_get()
        proposed, report = producer.build(
            observation(), base, previous, TODAY, fetch=fetch)
        self.assertEqual(report["eligibleUnknownSites"], 1)
        self.assertEqual(report["stateCounts"],
                         {"publisher_bound_openagenda_event_site_pair": 1},
                         report)
        self.assertEqual(len(proposed["approvals"]), 1)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        event = proposed["approvals"][0]
        site = proposed["venueApprovals"][0]
        self.assertEqual(event["officialEvidence"][1]["proofType"],
                         signer.OPENAGENDA_NEW_PROFILE)
        self.assertEqual(len(event["newArtists"]), 8)
        self.assertEqual(site["venue"]["name"], "Place Libre")
        self.assertEqual(site["venue"]["geoSource"], fixture.SITE_OSM)
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-point")
        self.assertEqual(site["venue"]["latitude"], 47.395)
        self.assertEqual(site["eventBinding"]["authoritySourceUrl"], URL)
        self.assertGreaterEqual(reads.count(OFFICIAL_EXPORT), 3)
        self.assertNotIn(URL, reads, "no second event website or HTML required")
        self.assertTrue(any(url.startswith("https://data.geopf.fr")
                            for url in reads))
        self.assertTrue(any("openstreetmap.org" in url for url in reads))
        self.assertEqual(previous, geo_fixture.before())

        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                previous, proposed, TODAY)), 1)
            published, stats = publisher.merge(base, base, proposed, TODAY)
        self.assertEqual(stats["newEvents"], 1, stats.get("held"))
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(published["events"][-1]["officialUrl"], URL)
        self.assertEqual(published["events"][-1]["venueId"],
                         published["venues"][-1]["id"])

    def test_openagenda_new_venue_fails_closed_on_false_identity_or_geography(self):
        base = geo_fixture.test_catalogue()
        reference = official()
        item = json.loads(reference)["events"][0]
        cases = (
            ("cancelled", {"status": 2}, None, None),
            ("wrong_uid", {"uid": 87654322}, None, None),
            ("wrong_agenda", {"origin": {"uid": 123456, "slug": "shotgun"}},
             None, None),
            ("wrong_agenda_slug", {"origin": {"uid": 9969608, "slug": "forged"}},
             None, None),
            ("wrong_date", {"firstDate": "2027-05-12"}, None, None),
            ("wrong_genre", {"keywords": {"fr": ["hardcore techno"]}},
             None, None),
            ("wrong_city", {"location": dict(item["location"], city="Paris")},
             None, None),
            ("wrong_country", {"location": dict(item["location"],
                                                countryCode="de")},
             None, None),
            ("wrong_gps", {"location": dict(item["location"],
                                           latitude=45.0)},
             None, None),
            ("wrong_government", {}, geo_fixture.ban(city="Paris"), None),
            ("wrong_named_site", {}, None, geo_fixture.osm_xml(
                name="Another venue")),
        )
        for name, changed, government, osm in cases:
            with self.subTest(name=name):
                fetch, _ = official_get(
                    changes=changed, gov=government, osm=osm)
                proposed, report = producer.build(
                    observation(), base, geo_fixture.before(), TODAY,
                    fetch=fetch)
                self.assertEqual(proposed, geo_fixture.before(), report)
                self.assertEqual(report["stateCounts"],
                                 {"held_original_or_named_site_unverified": 1},
                                 report)

    def test_french_overseas_places_are_eligible_without_city_allowlist(self):
        for code, postcode, department in (
            ("gp", "97110", "971"), ("mq", "97200", "972"),
            ("gf", "97300", "973"), ("re", "97400", "974"),
            ("yt", "97600", "976"), ("nc", "98800", "988"),
            ("pf", "98713", "987"), ("wf", "98600", "986"),
            ("pm", "97500", "975"),
        ):
            with self.subTest(country=code):
                place = producer._unpublished_location({
                    "location": {
                        "name": "Salle Libre", "city": "Ville Libre",
                        "postalCode": postcode,
                        "address": "15 rue Exemple, France",
                        "countryCode": code,
                    },
                })
                self.assertEqual(place["department"], department)
                self.assertEqual(place["name"], "Salle Libre")
                self.assertNotIn("latitude", place)
                self.assertNotIn("longitude", place)

    def test_discovery_never_authorizes_known_venue_or_old_date(self):
        base = geo_fixture.test_catalogue()
        fetch = lambda *_: self.fail("untrusted lead must not reach network")
        invalid = observation(date="2020-01-01")
        result, report = producer.build(
            invalid, base, geo_fixture.before(), TODAY, fetch=fetch)
        self.assertEqual(result, geo_fixture.before())
        self.assertEqual(report["eligibleUnknownSites"], 0)
        # A venue already present on the public map goes to existing-site
        # admission, never a parallel duplicate newly-created location.
        known = copy.deepcopy(base)
        known["venues"].append({
            "id": "already-signed-site", "name": "Place Libre",
            "city": "Tours",
        })
        result, report = producer.build(
            observation(), known, geo_fixture.before(), TODAY,
            fetch=fetch)
        self.assertEqual(result, geo_fixture.before())
        self.assertEqual(report["eligibleUnknownSites"], 0)


if __name__ == "__main__":
    unittest.main()
