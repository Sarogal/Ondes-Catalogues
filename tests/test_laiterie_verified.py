"""La Laiterie : preuves officielles nominatives, zéro date ou heure inférée."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from concerts_cloud_sync import LAITERIE_OFFICIAL_VERIFIED, validate_approval

CURRENT = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
VENUES = {x["id"]: x for x in CURRENT["venues"]}
ARTISTS = {x["id"]: x for x in CURRENT["artists"]}
TODAY = dt.date(2026, 11, 3)


def reviewed(spec_id):
    spec = LAITERIE_OFFICIAL_VERIFIED[spec_id]
    day = "2026-11-03"
    row = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": day,
        "officialEvidence": [
            {
                "url": spec["officialUrl"], "proofType": "official-organizer-or-venue",
                "checkedAt": day, "checkedFields": ["artists", "date", "venue", "genre"],
            },
            {
                "url": spec["calendarUrl"], "proofType": "first-party-venue-calendar",
                "checkedAt": day, "checkedFields": ["artists", "date", "venue", "genre"],
            },
        ],
        "event": {
            "id": spec_id, "title": spec["title"], "date": spec["date"],
            "time": None, "artistIds": spec["artistIds"],
            "venueId": "la-laiterie-strasbourg", "genres": spec["genres"],
            "status": "confirmed", "officialUrl": spec["officialUrl"],
            "sourceType": "salle", "organizer": "La Laiterie",
        },
        "newArtists": spec.get("newArtists", []),
    }
    if spec.get("organizerUrl"):
        row["officialEvidence"].append({
            "url":spec["organizerUrl"],
            "proofType":"independent-organizer-confirmation",
            "checkedAt":day,"checkedFields":["artists","date","venue"],
        })
    return row


class LaLaiterieApprovalsTests(unittest.TestCase):
    def test_nine_new_distinct_dates_valid_artists_and_door_time_unknown(self):
        self.assertEqual(len(LAITERIE_OFFICIAL_VERIFIED), 15)
        existing_dates = {
            e["date"] for e in CURRENT["events"] if e["venueId"] == "la-laiterie-strasbourg"
        }
        ids = {e["id"] for e in CURRENT["events"]}
        for key,spec in LAITERIE_OFFICIAL_VERIFIED.items():
            with self.subTest(key=key):
                if key in ids:
                    existing=next(e for e in CURRENT["events"] if e["id"]==key)
                    self.assertEqual(existing["date"],spec["date"])
                    self.assertEqual(existing["venueId"],"la-laiterie-strasbourg")
                    self.assertEqual(existing["artistIds"],spec["artistIds"])
                    self.assertIsNone(existing["time"])
                else:
                    self.assertNotIn(spec["date"],existing_dates)
                self.assertIsNone(spec["time"])
                self.assertTrue(spec["officialUrl"].startswith(
                    "https://www.artefact.org/la-laiterie/evenements/"))
                self.assertTrue(spec["calendarUrl"].startswith(
                    "https://www.artefact.org/evenements/page/"))
                approval=reviewed(key)
                if key not in ids or not spec.get("newArtists"):
                    event,added=validate_approval(approval,VENUES,ARTISTS,TODAY)
                    self.assertEqual(event,approval["event"])
                    self.assertEqual(set(added),{x["id"] for x in approval["newArtists"]})
                else:
                    self.assertTrue(all(a["id"] in ARTISTS
                                        and ARTISTS[a["id"]]["name"] == a["name"]
                                        for a in spec["newArtists"]))

    def test_wrong_identity_timestamp_or_official_source_must_fail(self):
        key = next(iter(LAITERIE_OFFICIAL_VERIFIED))
        valid = reviewed(key)
        mutations = {
            "invented-start": lambda x: x["event"].update(time="19:30"),
            "wrong-day": lambda x: x["event"].update(date="2027-02-06"),
            "wrong-artist": lambda x: x["event"]["artistIds"].reverse(),
            "wrong-organizer": lambda x: x["event"].update(venueId="fake-place"),
            "wrong-url": lambda x: x["event"].update(officialUrl="https://example.org/concert"),
            "fake-proof": lambda x: x["officialEvidence"][0].update(url="https://example.org"),
            "missing-calendar": lambda x: x["officialEvidence"].pop(),
            "fabricated-start-proof": lambda x: x["officialEvidence"][0]["checkedFields"].append("startTime"),
            "future-review": lambda x: x.update(reviewedAt="2026-11-04"),
            "untrusted-reviewer": lambda x: x.update(reviewedBy="automated-official-recheck"),
            "new-artist": lambda x: x.update(newArtists=[{"id":"fake","name":"Fake"}]),
        }
        for name,mutate in mutations.items():
            with self.subTest(case=name):
                item=copy.deepcopy(valid)
                mutate(item)
                with self.assertRaises((ValueError, KeyError)):
                    validate_approval(item,VENUES,ARTISTS,TODAY)

    def test_six_new_lineups_are_only_exactly_named_not_guessed_artists(self):
        new_rows=[
            (id, x) for id,x in LAITERIE_OFFICIAL_VERIFIED.items()
            if x.get("newArtists")
        ]
        self.assertEqual(len(new_rows),6)
        self.assertEqual(sum(len(x["newArtists"]) for _,x in new_rows),14)
        for ident,spec in new_rows:
            with self.subTest(id=ident):
                reviewed_row=reviewed(ident)
                if ident in {e["id"] for e in CURRENT["events"]}:
                    self.assertTrue(all(a["id"] in ARTISTS for a in spec["newArtists"]))
                    continue
                event,added=validate_approval(reviewed_row,VENUES,ARTISTS,TODAY)
                self.assertIsNone(event["time"])
                self.assertEqual(set(added),{x["id"] for x in spec["newArtists"]})
                forged=copy.deepcopy(reviewed_row)
                forged["newArtists"][0]["name"]="Personne inventée"
                with self.assertRaises((ValueError,KeyError)):
                    validate_approval(forged,VENUES,ARTISTS,TODAY)

    def test_sleeping_with_sirens_uses_corrected_promoter_band_spelling(self):
        key="go-c-20270217-strasbourg-sleeping-with-sirens"
        spec=LAITERIE_OFFICIAL_VERIFIED[key]
        self.assertEqual(spec["artistNames"],
                         ["Sleeping With Sirens","Arm's Length","Like Roses"])
        self.assertIn("www.livenation.com",spec["organizerUrl"])
        row=reviewed(key)
        self.assertEqual(len(row["officialEvidence"]),3)
        self.assertEqual(row["officialEvidence"][2]["proofType"],
                         "independent-organizer-confirmation")
        event,added=validate_approval(row,VENUES,ARTISTS,TODAY)
        self.assertIsNone(event["time"])
        self.assertIn("arms-length",added)
        wrong=copy.deepcopy(row)
        wrong["officialEvidence"].pop()
        with self.assertRaises((ValueError,KeyError)):
            validate_approval(wrong,VENUES,ARTISTS,TODAY)

    def test_reference_is_unchanged_by_verification(self):
        baseline=json.loads((ROOT / "docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
        self.assertEqual((len(baseline["events"]),len(baseline["venues"]),len(baseline["artists"])),
                         (127,53,193))


if __name__ == "__main__":
    unittest.main()
