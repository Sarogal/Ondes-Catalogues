"""Grenoble 27/02/2027 : publication strictement nominative et résiliente."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from concerts_cloud_sync import (
    TOURNEE_DU_COEUR_GRENOBLE_SIGNED_20261105 as SIGNED, validate_approval
)

CATALOG = json.loads(
    (ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026, 11, 5)

def approval():
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-05",
        "event": copy.deepcopy(SIGNED["event"]),
        "newArtists": [],
        "officialEvidence": [
            {**copy.deepcopy(spec), "checkedAt": "2026-11-05"}
            for spec in SIGNED["proofs"]
        ],
    }

class TourneeCoeurGrenobleCloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues = {v["id"]: v for v in CATALOG["venues"]}
        cls.artists = {a["id"]: a for a in CATALOG["artists"]}

    def test_verified_one_event_already_known_venue_and_artists(self):
        row = approval()
        event, added = validate_approval(
            row, self.venues, self.artists, TODAY)
        self.assertEqual(event, SIGNED["event"])
        self.assertEqual(added, {})
        self.assertIsNone(event["time"])
        self.assertNotIn(event["id"], {x["id"] for x in CATALOG["events"]})
        self.assertEqual(
            [self.artists[i]["name"] for i in event["artistIds"]],
            ["Cachemire", "La Phaze", "Bob's Not Dead"])

    def test_mutations_declined_without_relaxing_policy(self):
        attacks = [
            ("date", lambda x: x["event"].update(date="2027-02-26")),
            ("artists", lambda x: x["event"]["artistIds"].append("faux-groupe")),
            ("venue", lambda x: x["event"].update(venueId="la-laiterie-strasbourg")),
            ("time", lambda x: x["event"].update(time="20:00")),
            ("id", lambda x: x["event"].update(id="go-c-20270227-grenoble-fake")),
            ("url", lambda x: x["event"].update(
                officialUrl="https://www.la-belle-electrique.com/fr/agenda/other")),
            ("reviewer", lambda x: x.update(reviewedBy="automated-official-recheck")),
            ("old review", lambda x: x.update(reviewedAt="2026-10-01")),
            ("fake bill", lambda x: x["officialEvidence"][0].update(
                confirmedArtists=["Cachemire", "Groupe fictif"])),
            ("fake proof", lambda x: x["officialEvidence"][1].update(
                url="https://example.org/faux")),
            ("missing proof", lambda x: x["officialEvidence"].pop()),
            ("fake musical start", lambda x: x["officialEvidence"][0][
                "checkedFields"].append("concertStartTime")),
        ]
        for title, change in attacks:
            row = approval()
            change(row)
            with self.subTest(attack=title), self.assertRaises(
                    (ValueError, KeyError, TypeError)):
                validate_approval(row, self.venues, self.artists, TODAY)

if __name__ == "__main__":
    unittest.main()
