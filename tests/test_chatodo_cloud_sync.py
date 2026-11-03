"""Contrats de publication stricts Chato'do, sans accès réseau ni ajout direct JSON."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 3)
ID = "le-chatodo-blois"
CAT = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
KNOWN = {a["id"]: a for a in CAT["artists"] if a["id"] not in
         {"the-flying-bones", "wicked-vessel", "ultramoderne"}}
NAMES = {
    "the-flying-bones": "The Flying Bones",
    "wicked-vessel": "Wicked Vessel",
    "ultramoderne": "Ultramoderne",
}


def venue_row():
    spec = sync.PILOT_VENUES[ID]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-03",
        "venue": copy.deepcopy(spec["venue"]),
        "officialEvidence": [
            {"url": spec["officialUrl"], "proofType": "official-venue-address",
             "checkedAt": "2026-11-03",
             "checkedFields": ["name", "address", "postalCode", "city"]},
            {"url": spec["locationUrl"], "proofType": "openstreetmap-venue-way",
             "checkedAt": "2026-11-03",
             "checkedFields": ["venueName", "coordinates"]},
        ],
    }


def event_row(event_id):
    spec = sync.CHATODO_VERIFIED[event_id]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-03",
        "officialEvidence": [
            {"url": spec["officialUrl"],
             "proofType": "official-organizer-or-venue",
             "checkedAt": "2026-11-03",
             "checkedFields": ["artists", "date", "venue", "genre", "startTime"]},
            {"url": "https://chatodo.com/agenda/",
             "proofType": "first-party-venue-calendar",
             "checkedAt": "2026-11-03",
             "checkedFields": ["leadArtist", "dayMonth", "genre"]},
        ],
        "event": {
            "id": event_id, "title": spec["title"], "date": spec["date"],
            "artistIds": list(spec["artistIds"]), "time": spec["time"],
            "venueId": ID, "genres": list(spec["genres"]),
            "status": "confirmed", "officialUrl": spec["officialUrl"],
            "sourceType": "salle", "organizer": "Le Chato'do",
        },
        "newArtists": [{"id": aid, "name": NAMES[aid]}
                       for aid in spec["newArtistIds"]],
    }


class ChatodoCloudTests(unittest.TestCase):
    def test_verified_venue_has_exact_original_address_and_osm_building(self):
        approved = sync.validate_venue_approval(venue_row(), TODAY)
        self.assertEqual((approved["city"], approved["department"]), ("Blois", "41"))
        self.assertEqual((approved["address"], approved["postalCode"]),
                         ("113 avenue de Vendôme", "41000"))
        self.assertEqual((approved["latitude"], approved["longitude"]),
                         (47.60562, 1.31378))
        self.assertIn("entrée concerts", approved["geoPrecision"])

    def test_the_three_bills_pass_with_exact_artists_date_and_proofs(self):
        self.assertEqual(len(sync.CHATODO_VERIFIED), 3)
        for event_id, spec in sync.CHATODO_VERIFIED.items():
            with self.subTest(event_id=event_id):
                event, added = sync.validate_approval(
                    event_row(event_id), {ID: sync.PILOT_VENUES[ID]["venue"]},
                    KNOWN, TODAY)
                self.assertEqual(event["id"], event_id)
                self.assertIsNone(event["time"])
                self.assertEqual(list(added), spec["newArtistIds"])

    def test_wrong_location_fails_closed(self):
        for kind in ("gps", "address", "url", "review"):
            row = venue_row()
            if kind == "gps":
                row["venue"]["latitude"] += 0.03
            if kind == "address":
                row["venue"]["address"] = "adresse inventée"
            if kind == "url":
                row["officialEvidence"][1]["url"] = "https://example.com/location"
            if kind == "review":
                row["reviewedBy"] = "automated-official-recheck"
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                sync.validate_venue_approval(row, TODAY)

    def test_forged_bills_and_overclaimed_agenda_date_fail_closed(self):
        key = "go-c-20261112-blois-wicked-vessel"
        for kind in ("id", "date", "title", "lineup", "start", "genre",
                     "venue", "domain", "calendar", "calendar_year",
                     "reviewer", "stale", "new_artist_identity"):
            row = event_row(key)
            e = row["event"]
            if kind == "id":
                e["id"] = "go-c-20261112-blois-other"
            if kind == "date":
                e["date"] = "2026-11-13"
            if kind == "title":
                e["title"] = "Wicked Vessel"
            if kind == "lineup":
                e["artistIds"] = ["wicked-vessel"]
            if kind == "start":
                e["time"] = "18:30"
            if kind == "genre":
                e["genres"] = ["Jazz"]
            if kind == "venue":
                e["venueId"] = "le-chatodo-autre"
            if kind == "domain":
                e["officialUrl"] = "https://fake.example/agenda/evenement/wicked-vessel-ultramoderne/"
            if kind == "calendar":
                row["officialEvidence"][1]["url"] = "https://fake.example/agenda/"
            if kind == "calendar_year":
                row["officialEvidence"][1]["checkedFields"].append("date")
            if kind == "reviewer":
                row["reviewedBy"] = "automated-official-recheck"
            if kind == "stale":
                row["reviewedAt"] = "2026-10-10"
            if kind == "new_artist_identity":
                row["newArtists"][0]["name"] = "Faux artiste"
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                sync.validate_approval(
                    row, {ID: sync.PILOT_VENUES[ID]["venue"]}, KNOWN, TODAY)


if __name__ == "__main__":
    unittest.main()
