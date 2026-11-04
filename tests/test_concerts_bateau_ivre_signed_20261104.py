"""Bateau Ivre Tours: strict official source, indicative GPS, and five signed bills.

No direct modification of docs/grossesondes/concerts.json is permitted.
"""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from concerts_cloud_sync import (
    PILOT_VENUES, BATEAU_IVRE_SIGNED_20261104,
    validate_approval, validate_venue_approval,
)

PUBLIC = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
DAY = dt.date(2026, 11, 4)
VENUE_ID = "le-bateau-ivre-tours"
VENUE_SPEC = PILOT_VENUES[VENUE_ID]
EVENTS = BATEAU_IVRE_SIGNED_20261104


def venue_approval():
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-04",
        "venue": copy.deepcopy(VENUE_SPEC["venue"]),
        "officialEvidence": [
            {"url": VENUE_SPEC["officialUrl"], "proofType": "official-venue-address",
             "checkedAt": "2026-11-04",
             "checkedFields": ["name", "address", "postalCode", "city"]},
            {"url": VENUE_SPEC["locationUrl"],
             "proofType": "independent-tourism-event-gps",
             "checkedAt": "2026-11-04",
             "checkedFields": ["venueName", "coordinates"]},
        ],
    }


def event_approval(ident):
    spec = EVENTS[ident]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-04",
        "officialEvidence": [
            {"url": spec["officialUrl"], "proofType": "official-organizer-or-venue",
             "checkedAt": "2026-11-04",
             "checkedFields": ["artists", "date", "venue", "genre"]},
            {"url": spec["calendarUrl"], "proofType": "first-party-venue-calendar",
             "checkedAt": "2026-11-04",
             "checkedFields": spec["calendarFields"]},
        ],
        "event": {
            "id": ident, "title": spec["title"], "date": spec["date"],
            "time": None, "artistIds": spec["artistIds"],
            "venueId": VENUE_ID, "genres": spec["genres"],
            "status": "confirmed", "officialUrl": spec["officialUrl"],
            "sourceType": "salle",
        },
        "newArtists": [
            {"id": artist, "name": spec["artistNames"][i]}
            for i, artist in enumerate(spec["artistIds"])
            if artist in spec["newArtistIds"]
        ],
    }


class BateauIvreSignedPublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues = {x["id"]: x for x in PUBLIC["venues"]}
        cls.venues[VENUE_ID] = VENUE_SPEC["venue"]
        cls.artists = {x["id"]: x for x in PUBLIC["artists"]}

    def test_independently_reviewed_site_and_not_exact_entrance(self):
        already = {x["id"]: x for x in PUBLIC["venues"]}
        if VENUE_ID in already:
            self.assertEqual(already[VENUE_ID], VENUE_SPEC["venue"])
        venue = validate_venue_approval(venue_approval(), DAY)
        self.assertEqual(venue["city"], "Tours")
        self.assertEqual((venue["latitude"],venue["longitude"]),
                         (47.3844669,0.7013784))
        self.assertIn("indicatif", venue["geoPrecision"])
        self.assertIn("ne représente pas l'entrée exacte", venue["geoPrecision"])
        self.assertEqual(venue["geoSource"],VENUE_SPEC["locationUrl"])

    def test_five_real_bills_are_individually_restricted(self):
        self.assertEqual(len(EVENTS), 5)
        current_ids = {x["id"] for x in PUBLIC["events"]}
        already = {x["id"]: x for x in PUBLIC["events"]}
        for ident in current_ids & set(EVENTS):
            spec = EVENTS[ident]
            self.assertTrue(all(already[ident][field] == spec[field]
                                for field in ("title", "date", "time",
                                              "venueId", "artistIds", "genres",
                                              "officialUrl")))
        # Signed events may already be published when the workflow reruns.
        self.assertEqual(len({x["officialUrl"] for x in EVENTS.values()}), 5)
        for ident, spec in EVENTS.items():
            with self.subTest(ident=ident):
                event, added = validate_approval(
                    event_approval(ident), self.venues, self.artists, DAY)
                self.assertEqual(event["date"],spec["date"])
                self.assertIsNone(event["time"])
                self.assertEqual(event["venueId"], VENUE_ID)
                self.assertEqual(set(added),set(spec["newArtistIds"]))
                self.assertFalse(any(
                    existing["date"] == event["date"] and
                    existing["venueId"] == event["venueId"] and
                    set(existing["artistIds"]) & set(event["artistIds"])
                    for existing in PUBLIC["events"]))

    def test_venue_proof_and_coordinates_cannot_be_forged(self):
        for label, mutate in (
            ("wrong-latitude", lambda row: row["venue"].update(latitude=48.3)),
            ("wrong-address", lambda row: row["venue"].update(city="Dijon")),
            ("fake-coordinate-source", lambda row:
             row["officialEvidence"][1].update(url="https://example.com/gps")),
            ("missing-coordinate-proof", lambda row: row["officialEvidence"].pop()),
        ):
            row = venue_approval()
            mutate(row)
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_venue_approval(row, DAY)

    def test_no_inferred_start_fabricated_lineup_year_or_approval(self):
        ident = next(iter(EVENTS))
        for label, mutate in (
            ("wrong-date", lambda x: x["event"].update(date="2026-11-07")),
            ("fake-start", lambda x: x["event"].update(time="20:00")),
            ("renamed-act", lambda x: x["event"].update(title="Concert fictif")),
            ("fake-artist", lambda x: x["newArtists"][0].update(name="Fake Band")),
            ("wrong-room", lambda x: x["event"].update(venueId="le-ferrailleur-nantes")),
            ("wrong-source", lambda x: x["officialEvidence"][0].update(url="https://example.org")),
            ("no-index", lambda x: x["officialEvidence"].pop()),
            ("door-as-start", lambda x: x["officialEvidence"][0]["checkedFields"].append("concertStartTime")),
            ("altered-calendar-year", lambda x: x["officialEvidence"][1]["checkedFields"].append("yearIndex")),
            ("unapproved",lambda x:x.update(reviewDecision="candidate")),
        ):
            row=event_approval(ident)
            mutate(row)
            with self.subTest(label=label), self.assertRaises(ValueError):
                validate_approval(row, self.venues, self.artists, DAY)

    def test_unknown_show_or_recycled_url_is_refused(self):
        row=event_approval(next(iter(EVENTS)))
        row["event"]["id"]="go-c-20261106-tours-fake-event"
        with self.assertRaises(ValueError):
            validate_approval(row,self.venues,self.artists,DAY)
        row["event"]["officialUrl"]="https://www.bateauivre.coop/%C3%A9v%C3%A8nements/fake/"
        with self.assertRaises(ValueError):
            validate_approval(row,self.venues,self.artists,DAY)


if __name__ == "__main__":
    unittest.main()
