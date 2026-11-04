"""Quatre affiches Colmar/Limoges : preuves par champ et sécurité anti-falsification."""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from scripts import concerts_cloud_sync as sync

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
DAY = dt.date(2026, 11, 4)

IDS = (
    "go-c-20261209-colmar-darvaza",
    "go-c-20270213-colmar-8-6-crew",
    "go-c-20261106-limoges-7weeks",
    "go-c-20261127-limoges-gwendoline",
)

def signed(ident):
    spec = sync.COLMAR_LIMOGES_VERIFIED_20261104[ident]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DAY.isoformat(),
        "officialEvidence": [
            {"url": p["url"], "proofType": p["proofType"],
             "checkedAt": DAY.isoformat(),
             "checkedFields": list(p["requiredFields"])}
            for p in spec["proofs"]
        ],
        "event": {
            "id": ident, "title": spec["title"], "date": spec["date"],
            "time": None, "artistIds": list(spec["artistIds"]),
            "venueId": spec["venueId"], "genres": list(spec["genres"]),
            "status": "confirmed", "officialUrl": spec["officialUrl"],
            "sourceType": "salle",
        },
        "newArtists": copy.deepcopy(spec["newArtists"]),
    }

def check(approval):
    known = {a["id"]: a for a in CATALOGUE["artists"]
             if a["id"] not in {n["id"] for n in approval["newArtists"]}}
    venues = {v["id"]: v for v in CATALOGUE["venues"]}
    return sync.validate_approval(approval, venues, known, DAY)


class ColmarLimogesSignatures(unittest.TestCase):
    def test_four_exact_first_party_programmes(self):
        specs = sync.COLMAR_LIMOGES_VERIFIED_20261104
        self.assertEqual(set(specs), set(IDS))
        existing = {e["id"]: e for e in CATALOGUE["events"]}
        for ident in IDS:
            with self.subTest(ident=ident):
                row = signed(ident)
                event, added = check(row)
                self.assertEqual(event["id"], ident)
                self.assertIsNone(event["time"])
                self.assertEqual(len(row["officialEvidence"]), 2)
                self.assertEqual(set(added), {a["id"] for a in row["newArtists"]})
                if ident in existing:
                    for key in ("id", "title", "date", "artistIds", "venueId",
                                "officialUrl", "genres", "status"):
                        self.assertEqual(existing[ident][key], event[key])

    def test_incomplete_year_source_does_not_claim_complete_date(self):
        expected = {
            "go-c-20270213-colmar-8-6-crew": ({"artists", "dayMonth", "venue", "genre"}, 1),
            "go-c-20261106-limoges-7weeks": ({"artists", "dayMonth", "venue", "genre"}, 0),
            "go-c-20261127-limoges-gwendoline": ({"artists", "dayMonth", "venue", "genre"}, 0),
        }
        for ident, (fields, index) in expected.items():
            row = signed(ident)
            self.assertEqual(set(row["officialEvidence"][index]["checkedFields"]), fields)
            self.assertNotIn("date", fields)
            self.assertIsNone(check(row)[0]["time"])

    def test_swapped_programme_location_artists_hours_and_proofs_fail_closed(self):
        for ident in IDS:
            variants = []
            v = signed(ident)
            v["event"]["title"] += " + Invité inventé"
            variants.append(v)
            v = signed(ident)
            v["event"]["date"] = "2027-06-20"
            variants.append(v)
            v = signed(ident)
            v["event"]["venueId"] = "le-ferrailleur-nantes"
            variants.append(v)
            v = signed(ident)
            v["event"]["time"] = "20:00"
            variants.append(v)
            v = signed(ident)
            v["event"]["genres"] = ["Electro"]
            variants.append(v)
            v = signed(ident)
            v["officialEvidence"].pop()
            variants.append(v)
            v = signed(ident)
            v["officialEvidence"][0]["url"] = "https://example.com/unconfirmed"
            variants.append(v)
            v = signed(ident)
            v["officialEvidence"][1]["checkedFields"].append("date")
            variants.append(v)
            v = signed(ident)
            v["officialEvidence"][0]["checkedFields"].append("concertStartTime")
            variants.append(v)
            v = signed(ident)
            v["newArtists"].append({"id": "extra-guest", "name": "Extra Guest"})
            variants.append(v)
            for i, row in enumerate(variants):
                with self.subTest(id=ident, mutation=i):
                    with self.assertRaises((ValueError, KeyError, TypeError)):
                        check(row)

    def test_unauthorized_new_event_same_venue_is_not_allowlisted(self):
        for ident in IDS:
            row = signed(ident)
            row["event"]["id"] = ident + "-nouveau"
            with self.subTest(ident=ident):
                with self.assertRaises((ValueError, KeyError)):
                    check(row)


if __name__ == "__main__":
    unittest.main()
