"""Publisher regressions for independently attested one-off event locations.

All facts, pages and URLs in these fixtures are synthetic; no network and
no public catalogue changes. The real approved source LIST is read only.
"""
import copy
import datetime as dt
import unittest

from scripts import concerts_cloud_sync as sync
from scripts import concert_event_site_contract as site

TODAY = dt.date(2026, 11, 19)
EVENT_DATE = "2027-04-27"
EVENT_ID = "go-c-20270427-paris-experimental-metal"
EVENT_URL = "https://7weeks.fr/concerts/fixture-paris-open-air-2027/"
AUTHORITY = "https://7weeks.fr/concerts/"
GEO = "https://www.openstreetmap.org/way/123456789"
NAME = "Esplanade des Tests"
CITY = "Paris"


def fixtures():
    venue = {
        "id": site.site_id(NAME, CITY, GEO),
        "name": NAME, "address": "Parvis de l'esplanade",
        "postalCode": "75007", "city": CITY, "department": "75",
        "region": "Île-de-France", "latitude": 48.858, "longitude": 2.294,
        "geoPrecision": "named-site-area", "geoSource": GEO,
    }
    event = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "officialEvidence": [{
            "url": EVENT_URL, "proofType": "official-organizer-or-venue",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
        }],
        "event": {
            "id": EVENT_ID, "date": EVENT_DATE, "officialUrl": EVENT_URL,
            "venueId": venue["id"], "status": "confirmed",
            "artistIds": ["7weeks"], "title": "Experimental Metal Outdoor",
            "genres": ["Metal"], "time": None, "sourceType": "organisateur",
        },
        "newArtists": [],
    }
    row = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "venueKind": "independent-event-site-v1",
        "locationKind": "public-square",
        "venue": venue,
        "eventBinding": {
            "eventId": EVENT_ID, "eventDate": EVENT_DATE,
            "eventOfficialUrl": EVENT_URL,
            "authoritySourceUrl": AUTHORITY,
            "authorityArtistId": "7weeks",
        },
        "officialEvidence": [{
            "url": EVENT_URL, "proofType": "official-event-location",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": ["eventId", "date", "venueName", "city", "country"],
            "eventId": EVENT_ID, "venueName": NAME, "city": CITY, "country": "FR",
        }, {
            "url": GEO, "proofType": "independent-osm-site",
            "checkedAt": TODAY.isoformat(),
            "checkedFields": ["venueName", "city", "coordinates", "country"],
            "venueName": NAME, "city": CITY, "country": "FR",
            "latitude": 48.858, "longitude": 2.294,
            "geoPrecision": "named-site-area",
        }],
    }
    return row, [event]


class EventSitePublisherContractTests(unittest.TestCase):
    def test_unlisted_one_off_public_square_can_be_validated_without_permanent_venue_spec(self):
        row, events = fixtures()
        original = copy.deepcopy((row, events))
        self.assertNotIn(row["venue"]["id"], sync.PILOT_VENUES)
        result = sync.validate_venue_approval(row, TODAY, events)
        self.assertEqual(result, row["venue"])
        self.assertIsNot(result, row["venue"])
        self.assertEqual((row, events), original)

    def test_anonymous_source_or_candidate_without_event_review_cannot_register_site(self):
        row, events = fixtures()
        cases = (
            ("no-ledger", lambda r, e: e.clear()),
            ("private-candidate-reviewer", lambda r, e: r.update(reviewedBy="candidate")),
            ("not-an-event-site", lambda r, e: r.update(venueKind="newVenueToReview")),
            ("unknown-promoter", lambda r, e: r["eventBinding"].update(
                authoritySourceUrl="https://unreviewed.example/tour/")),
            ("other-event", lambda r, e: r["eventBinding"].update(eventId="go-c-20270428-fake")),
            ("other-date", lambda r, e: r["eventBinding"].update(eventDate="2027-04-28")),
            ("other-artist", lambda r, e: r["eventBinding"].update(authorityArtistId="other")),
            ("event-url-changed", lambda r, e: r["eventBinding"].update(
                eventOfficialUrl="https://7weeks.fr/concerts/fake-elsewhere/")),
            ("wrong-source-genre", lambda r, e: e[0]["officialEvidence"][0].update(
                checkedFields=["artists", "date", "venue"])),
            ("event-unsigned", lambda r, e: e[0].update(reviewedBy="candidate")),
            ("different-site", lambda r, e: e[0]["event"].update(venueId="random")),
            ("date-after-event", lambda r, e: r.update(reviewedAt="2027-05-01")),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                r, e = copy.deepcopy((row, events))
                mutate(r, e)
                with self.assertRaises(ValueError):
                    sync.validate_venue_approval(r, TODAY, e)

    def test_site_geography_and_independent_source_are_not_guessed(self):
        row, events = fixtures()
        cases = (
            ("fake-coordinates", lambda r: r["venue"].update(latitude=49.9)),
            ("invented-address", lambda r: r["venue"].update(address="À vérifier")),
            ("city-centroid", lambda r: r["venue"].update(geoPrecision="city-centre")),
            ("unknown-postcode", lambda r: r["venue"].update(postalCode="")),
            ("foreign-coordinate", lambda r: r["venue"].update(latitude=74.4)),
            ("booleans-not-coordinates", lambda r: r["venue"].update(latitude=True)),
            ("same-artist-domain", lambda r: r["venue"].update(geoSource=EVENT_URL)),
            ("openstreetmap-search", lambda r: r["venue"].update(
                geoSource="https://www.openstreetmap.org/search?query=paris")),
            ("forged-map-pin", lambda r: r["officialEvidence"][1].update(longitude=2.33)),
            ("missing-osm-feature", lambda r: r["officialEvidence"].pop()),
            ("wrong-geo-country", lambda r: r["officialEvidence"][1].update(country="BE")),
            ("location-name-substituted", lambda r: r["venue"].update(name="Tour Mystère")),
            ("unlisted-extra-field", lambda r: r["venue"].update(publicationAllowed=True)),
            ("bad-location-category", lambda r: r.update(locationKind="superstar")),
            ("venue-approval-prop", lambda r: r.update(publicationAllowed=True)),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                r = copy.deepcopy(row)
                mutate(r)
                with self.assertRaises(ValueError):
                    sync.validate_venue_approval(r, TODAY, events)

    def test_source_registry_is_specific_and_no_placeholder_metallica_event_is_authorized(self):
        row, events = fixtures()
        row["eventBinding"]["authoritySourceUrl"] = "https://metallica.com/"
        row["eventBinding"]["authorityArtistId"] = "metallica"
        with self.assertRaises(ValueError):
            site.validate(row, TODAY, events)
        self.assertEqual(events[0]["event"]["title"], "Experimental Metal Outdoor")

    def test_full_publisher_adds_site_and_concert_in_same_atomic_catalogue(self):
        import json
        reference = json.loads(sync.REFERENCE.read_text(encoding="utf-8"))
        current = copy.deepcopy(reference)
        site_row, event_entries = fixtures()
        approved = {"schema": sync.SCHEMA,
                    "approvals": event_entries, "venueApprovals": [site_row]}
        result, counts = sync.merge(reference, current, approved, TODAY)
        self.assertEqual(counts["newVenues"], 1)
        self.assertEqual(counts["newEvents"], 1)
        self.assertIn(site_row["venue"]["id"], [v["id"] for v in result["venues"]])
        self.assertIn(EVENT_ID, [e["id"] for e in result["events"]])
        self.assertEqual(current, reference)
        # Previously published site+concert remain valid after replay;
        # the ledger authorizes them, not a new permanent venue manifest.
        again, repeated = sync.merge(reference, result, approved, TODAY)
        self.assertEqual(repeated["newVenues"], 0)
        self.assertEqual(repeated["newEvents"], 0)
        self.assertEqual(again["events"], result["events"])
        self.assertEqual(again["venues"], result["venues"])

    def test_unvalidated_event_cannot_leave_an_orphan_geographic_pin(self):
        import json
        reference = json.loads(sync.REFERENCE.read_text(encoding="utf-8"))
        site_row, event_entries = fixtures()
        event_entries[0]["event"]["sourceType"] = "unrecognized"
        # The event-site validator can match the identity in the ledger,
        # but the regular full publisher must still approve the event.
        approved = {"schema": sync.SCHEMA,
                    "approvals": event_entries, "venueApprovals": [site_row]}
        result, counts = sync.merge(
            reference, copy.deepcopy(reference), approved, TODAY)
        self.assertEqual(counts["newVenues"], 0)
        self.assertEqual(counts["newEvents"], 0)
        self.assertNotIn(site_row["venue"]["id"],
                         [v["id"] for v in result["venues"]])

    def test_stable_id_does_not_require_hall_known_in_advance(self):
        self.assertEqual(
            site.site_id(NAME, CITY, GEO),
            site.site_id(NAME, CITY, GEO))
        # Different concerts at the SAME geographic feature can share one
        # catalogue pin. Different OSM features cannot impersonate it.
        self.assertNotEqual(
            site.site_id(NAME, CITY, GEO),
            site.site_id(NAME, CITY, "https://www.openstreetmap.org/way/987654321"))


if __name__ == "__main__":
    unittest.main()
