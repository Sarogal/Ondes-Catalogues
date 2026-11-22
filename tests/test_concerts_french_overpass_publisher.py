"""Third read-only Overpass fallback reaches real OA new venue Publisher.

All HTML, JSON and OSM contents are synthetic. No remote call or approval
shortcut: official OA UID + BAN address + a SINGLE named OSM feature are
replayed through the actual private preflight and production merge.
"""
import unittest
from unittest import mock

from automation.concerts import approval_preflight
from scripts import concert_dynamic_new_site_source as signer
from scripts import concerts_cloud_sync as publisher
import test_concerts_openagenda_new_site_publisher as fixture
import test_concerts_dynamic_existing_venue as existing

FR = "https://overpass.openstreetmap.fr/api/interpreter?"
SOURCES = (
    "https://api.openstreetmap.org/",
    "https://overpass.private.coffee/",
    "https://overpass-api.de/",
)


def third_only(*, changed_osm=None, final_available=True):
    original, seen = fixture.official_get()
    osm = changed_osm if changed_osm is not None else (
        fixture.geo_fixture.osm_xml())
    def fetch(url, cache):
        if url.startswith(SOURCES[0]):
            seen.append(url)
            raise ValueError("editing map API rejects requests")
        if url.startswith(SOURCES[1]):
            seen.append(url)
            raise TimeoutError("first read-only provider timed out")
        if url.startswith(SOURCES[2]):
            seen.append(url)
            raise ValueError("robots.txt forbids the candidate page")
        if url.startswith(FR):
            seen.append(url)
            if not final_available:
                raise TimeoutError("third provider unavailable")
            return osm
        return original(url, cache)
    return fetch, seen


class ThirdReadOnlyPublisherTests(unittest.TestCase):
    def setUp(self):
        old = publisher.NEW_REFERENCE_GEO_SOURCES.pop(
            existing.VENUE_ID, None)
        self.assertIsNotNone(old)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            existing.VENUE_ID, old))

    def test_one_openagenda_event_new_room_and_bands_publish_after_two_osm_failures(self):
        base = fixture.geo_fixture.test_catalogue()
        before = fixture.geo_fixture.before()
        fetch, seen = third_only()
        proposed, report = fixture.producer.build(
            fixture.observation(), base, before, fixture.TODAY, fetch=fetch)
        self.assertEqual(report["stateCounts"], {
            "publisher_bound_openagenda_event_site_pair": 1}, report)
        self.assertEqual(len(proposed["approvals"]), 1)
        self.assertEqual(len(proposed["venueApprovals"]), 1)
        self.assertEqual(proposed["venueApprovals"][0]["venue"]["geoSource"],
                         fixture.fixture.SITE_OSM)
        self.assertTrue(any(url.startswith(FR) for url in seen))
        self.assertTrue(any(url.startswith(SOURCES[2]) for url in seen))
        with mock.patch.object(signer.probe, "safe_fetch", side_effect=fetch):
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposed, fixture.TODAY)), 1)
            new_catalogue, stats = publisher.merge(
                base, base, proposed, fixture.TODAY)
        self.assertEqual(stats["newEvents"], 1, stats.get("held"))
        self.assertEqual(stats["newVenues"], 1)
        self.assertEqual(stats["newArtists"], 8)
        self.assertEqual(new_catalogue["events"][-1]["officialUrl"],
                         fixture.URL)

    def test_bad_named_site_cannot_be_replaced_or_published(self):
        base = fixture.geo_fixture.test_catalogue()
        before = fixture.geo_fixture.before()
        wrong = fixture.geo_fixture.osm_xml(name="Impostor Venue")
        fetch, seen = third_only(changed_osm=wrong)
        proposed, report = fixture.producer.build(
            fixture.observation(), base, before, fixture.TODAY, fetch=fetch)
        self.assertEqual(proposed, before)
        self.assertEqual(report["stateCounts"], {
            "held_original_or_named_site_unverified": 1}, report)
        self.assertTrue(any(url.startswith(FR) for url in seen))

    def test_all_osm_services_unavailable_is_never_approval(self):
        base = fixture.geo_fixture.test_catalogue()
        before = fixture.geo_fixture.before()
        fetch, _ = third_only(final_available=False)
        proposed, report = fixture.producer.build(
            fixture.observation(), base, before, fixture.TODAY, fetch=fetch)
        self.assertEqual(proposed, before)
        self.assertEqual(report["stateCounts"], {
            "held_original_or_named_site_unverified": 1}, report)


if __name__ == "__main__":
    unittest.main()
