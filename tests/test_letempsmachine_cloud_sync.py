"""Publication strictement nominative du Temps Machine: aucune heure déduite."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

TODAY = dt.date(2026, 11, 3)
V = "le-temps-machine-joue-les-tours"
E = "go-c-20261119-joue-les-tours-birdstone-marave"
CAT = json.loads((Path(__file__).resolve().parents[1]/
    "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
KNOWN = {x["id"]: x for x in CAT["artists"]}
NAMES = {"birdstone": "Birdstone", "marave": "Marave"}


def venue():
    spec = sync.PILOT_VENUES[V]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-03",
        "venue": copy.deepcopy(spec["venue"]),
        "officialEvidence": [
            {"url": spec["officialUrl"], "proofType": "official-venue-address",
             "checkedAt": "2026-11-03", "checkedFields":
             ["name", "address", "postalCode", "city"]},
            {"url": spec["locationUrl"], "proofType": "independent-venue-gps",
             "checkedAt": "2026-11-03", "checkedFields":
             ["venueName", "coordinates"]},
        ],
    }


def event():
    spec = sync.TEMPS_MACHINE_VERIFIED[E]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-03",
        "officialEvidence": [
            {"url": spec["officialUrl"],
             "proofType": "official-organizer-or-venue",
             "checkedAt": "2026-11-03",
             "checkedFields": ["artists", "venue", "date", "genre"]},
            {"url": "https://letempsmachine.com/agenda?category=All&location=All",
             "proofType": "first-party-venue-calendar",
             "checkedAt": "2026-11-03",
             "checkedFields": ["artists", "date", "genre"]},
        ],
        "event": {
            "id": E, "title": spec["title"], "date": spec["date"],
            "time": spec["time"], "artistIds": list(spec["artistIds"]),
            "venueId": V, "genres": list(spec["genres"]),
            "status": "confirmed", "officialUrl": spec["officialUrl"],
            "sourceType": "salle", "organizer": "Le Temps Machine",
        },
        "newArtists": [{"id": k, "name": NAMES[k]}
                       for k in spec["newArtistIds"]],
    }


class TempsMachineCloudTests(unittest.TestCase):
    def test_first_party_address_and_independent_location_only(self):
        v = sync.validate_venue_approval(venue(), TODAY)
        self.assertEqual((v["city"], v["postalCode"]), ("Joué-lès-Tours", "37300"))
        self.assertEqual((v["latitude"], v["longitude"]), (47.352189, 0.664716))
        self.assertIn("indicatives", v["geoPrecision"])

    def test_one_nominal_bill_only_two_real_artists_and_no_door_time(self):
        self.assertEqual(len(sync.TEMPS_MACHINE_VERIFIED), 1)
        e, added = sync.validate_approval(
            event(), {V: sync.PILOT_VENUES[V]["venue"]}, KNOWN, TODAY)
        self.assertEqual((e["id"], e["artistIds"]), (E, ["birdstone", "marave"]))
        self.assertIsNone(e["time"])
        self.assertEqual(list(added), ["birdstone", "marave"])

    def test_forgeries_cannot_change_gps_or_venue(self):
        for kind in ("latitude", "longitude", "address", "source", "proof", "review"):
            row = venue()
            if kind == "latitude":
                row["venue"]["latitude"] += 0.2
            if kind == "longitude":
                row["venue"]["longitude"] -= 0.2
            if kind == "address":
                row["venue"]["address"] = "adresse incorrecte"
            if kind == "source":
                row["venue"]["geoSource"] = "https://example.com"
            if kind == "proof":
                row["officialEvidence"][1]["url"] = "https://example.com"
            if kind == "review":
                row["reviewedBy"] = "automated-official-recheck"
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                sync.validate_venue_approval(row, TODAY)

    def test_wrong_date_artists_genres_url_review_and_time_are_rejected(self):
        for kind in ("id", "date", "title", "artists", "time", "genres",
                     "venue", "url", "calendar", "review", "old", "artist_identity",
                     "claimed_start"):
            row = event()
            ev = row["event"]
            if kind == "id":
                ev["id"] = "go-c-20261120-joue-les-tours-invented"
            if kind == "date":
                ev["date"] = "2026-11-20"
            if kind == "title":
                ev["title"] = "Birdstone sans Marave"
            if kind == "artists":
                ev["artistIds"] = ["birdstone"]
            if kind == "time":
                ev["time"] = "19:30"
            if kind == "genres":
                ev["genres"] = ["Jazz"]
            if kind == "venue":
                ev["venueId"] = "wrong"
            if kind == "url":
                ev["officialUrl"] = "https://example.org/agenda/release-party-birdstone-marave"
            if kind == "calendar":
                row["officialEvidence"][1]["url"] = "https://example.org/agenda"
            if kind == "review":
                row["reviewedBy"] = "automated"
            if kind == "old":
                row["reviewedAt"] = "2026-10-01"
            if kind == "artist_identity":
                row["newArtists"][1]["name"] = "Un autre artiste"
            if kind == "claimed_start":
                row["officialEvidence"][0]["checkedFields"].append("concertStartTime")
            with self.subTest(kind=kind), self.assertRaises((ValueError, KeyError)):
                sync.validate_approval(
                    row, {V: sync.PILOT_VENUES[V]["venue"]}, KNOWN, TODAY)


if __name__ == "__main__":
    unittest.main()
