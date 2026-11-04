"""Echonova, Saint-Avé: exact first-party concert and independently located venue.

All tests are offline. No generic venue bypass, unnamed guest or inferred start.
"""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from scripts.concerts_cloud_sync import (
    ECHONOVA_SIGNED_20261104, PILOT_VENUES,
    validate_venue_approval, validate_approval,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-11-04"
VENUE_ID = "l-echonova-saint-ave"
IDS = ("go-c-20261203-saint-ave-eiffel",
       "go-c-20270206-saint-ave-meteora-systemize")


def venue_approval():
    spec = PILOT_VENUES[VENUE_ID]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DATE,
        "venue": copy.deepcopy(spec["venue"]),
        "officialEvidence": [
            {"url": spec["officialUrl"], "proofType": "official-venue-address",
             "checkedAt": DATE,
             "checkedFields": ["name", "address", "postalCode", "city"]},
            {"url": spec["locationUrl"],
             "proofType": spec["locationProofType"],
             "checkedAt": DATE,
             "checkedFields": ["venueName", "coordinates"]},
        ],
    }


def concert_approval(event_id):
    spec = ECHONOVA_SIGNED_20261104[event_id]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DATE,
        "officialEvidence": [
            {"url": spec["officialUrl"],
             "proofType": "official-organizer-or-venue",
             "checkedAt": DATE,
             "checkedFields": copy.deepcopy(spec["firstPartyFields"])},
            {"url": spec["ticketingUrl"],
             "proofType": "independent-ticketing-venue-list",
             "checkedAt": DATE,
             "checkedFields": copy.deepcopy(spec["ticketingFields"])},
        ],
        "event": {
            "id": event_id, "title": spec["title"],
            "date": spec["date"], "time": spec["time"],
            "venueId": VENUE_ID,
            "artistIds": copy.deepcopy(spec["artistIds"]),
            "genres": copy.deepcopy(spec["genres"]),
            "status": "confirmed",
            "officialUrl": spec["officialUrl"],
            "sourceType": "salle",
        },
        "newArtists": copy.deepcopy(spec["newArtists"]),
    }


class EchonovaSignedPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = json.loads(
            (ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues = {v["id"]: v for v in cls.catalogue["venues"]}
        cls.venues[VENUE_ID] = copy.deepcopy(PILOT_VENUES[VENUE_ID]["venue"])
        new_ids = {a["id"] for event_id in IDS
                   for a in ECHONOVA_SIGNED_20261104[event_id]["newArtists"]}
        cls.artists = {a["id"]: a for a in cls.catalogue["artists"]
                       if a["id"] not in new_ids}
        cls.today = dt.date.fromisoformat(DATE)

    def test_exact_address_and_independently_sourced_indicative_coordinates(self):
        row = venue_approval()
        venue = validate_venue_approval(row, self.today)
        self.assertEqual(venue["id"], VENUE_ID)
        self.assertEqual((venue["city"], venue["postalCode"]),
                         ("Saint-Avé", "56890"))
        self.assertIn("indicatif", venue["geoPrecision"])
        for bad in (
            {"latitude": 0.0}, {"address": "Unknown street"},
            {"geoSource": "https://example.net/random"}
        ):
            altered = copy.deepcopy(row)
            altered["venue"].update(bad)
            with self.subTest(altered=bad), self.assertRaises(ValueError):
                validate_venue_approval(altered, self.today)
        missing = copy.deepcopy(row)
        missing["officialEvidence"].pop()
        with self.assertRaises(ValueError):
            validate_venue_approval(missing, self.today)

    def test_two_named_events_are_signed_without_guest_or_guessed_time(self):
        self.assertEqual(set(ECHONOVA_SIGNED_20261104), set(IDS))
        public_ids = {e["id"] for e in self.catalogue["events"]}
        for ident in IDS:
            with self.subTest(ident=ident):
                spec = ECHONOVA_SIGNED_20261104[ident]
                if ident not in public_ids:
                    self.assertEqual(spec["venueId"], VENUE_ID)
                event, added = validate_approval(
                    concert_approval(ident), self.venues,
                    self.artists, self.today)
                self.assertEqual(event["id"], ident)
                self.assertEqual(set(added),
                                 {a["id"] for a in spec["newArtists"]})
                self.assertNotIn("guest", event["title"].casefold())
                self.assertEqual(event["time"],
                                 "20:30" if ident.endswith("eiffel") else None)

    def test_wrong_date_hours_venue_source_or_artist_is_blocked(self):
        for ident in IDS:
            base = concert_approval(ident)
            for label, mutate in (
                ("title", lambda x: x["event"].update(title="Invented Bill")),
                ("date", lambda x: x["event"].update(date="2027-09-01")),
                ("time", lambda x: x["event"].update(time="23:15")),
                ("venue", lambda x: x["event"].update(venueId="le-rex-toulouse")),
                ("url", lambda x: x["event"].update(
                    officialUrl="https://example.net/event/unverified/")),
                ("extra-act", lambda x: x["event"]["artistIds"].append("guest")),
                ("fake-artist", lambda x: x["newArtists"][0].update(name="Invented")),
                ("missing-proof", lambda x: x["officialEvidence"].pop()),
                ("wrong-proof", lambda x: x["officialEvidence"][1].update(
                    url="https://fake.example/venue/")),
                ("fake-door-clock", lambda x: x["officialEvidence"][0][
                    "checkedFields"].append("doorTime")),
            ):
                altered = copy.deepcopy(base)
                mutate(altered)
                with self.subTest(id=ident, change=label):
                    with self.assertRaises((ValueError, KeyError, TypeError)):
                        validate_approval(altered, self.venues,
                                          self.artists, self.today)


if __name__ == "__main__":
    unittest.main()
