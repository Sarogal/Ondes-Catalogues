"""Contrôles de conservation et des quatre approbations ouest/Centre, 3 novembre 2026."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
CASES = {
    "go-c-20261209-brest-fff-howlin-jaws": {
        "date": "2026-12-09",
        "venue": "la-carene-brest",
        "artists": ["fff", "howlin-jaws"],
        "url": "https://www.lacarene.fr/fff-howlin-jaws.html",
        "secondary": ("first-party-venue-calendar", "https://www.lacarene.fr/-agenda-.html"),
    },
    "go-c-20270402-brest-les-fatals-picards": {
        "date": "2027-04-02",
        "venue": "la-carene-brest",
        "artists": ["les-fatals-picards"],
        "url": "https://www.lacarene.fr/les-fatals-picards.html",
        "secondary": ("first-party-venue-calendar", "https://www.lacarene.fr/-agenda-.html"),
    },
    "go-c-20270219-orleans-burning-heads": {
        "date": "2027-02-19",
        "venue": "l-astrolabe-orleans",
        "artists": ["burning-heads", "not-scientists"],
        "url": "https://www.lastrolabe.org/agenda/burning-heads-not-scientists/",
        "secondary": ("first-party-venue-calendar",
                      "https://www.lastrolabe.org/agenda/"),
    },
    "go-c-20270212-rouen-johnny-mafia-les-agamemnonz": {
        "date": "2027-02-12",
        "venue": "le-106-rouen",
        "artists": ["johnny-mafia", "les-agamemnonz"],
        "url": "https://le106.com/agenda/johnny-mafia-les-agamemnonz",
        "secondary": ("first-party-venue-calendar", "https://le106.com/agenda"),
    },
}


class WestCentreApprovalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))["approvals"]
        cls.by_id = {x["event"]["id"]: x for x in cls.rows}

    def test_all_prior_records_kept_and_identifiers_unique(self):
        self.assertGreaterEqual(len(self.rows), 111)
        self.assertLessEqual(len(self.rows), 400)
        self.assertEqual(len(self.by_id), len(self.rows))

    def test_four_exact_verified_lineups_without_invented_times(self):
        for event_id, expected in CASES.items():
            with self.subTest(event=event_id):
                row = self.by_id[event_id]
                event = row["event"]
                self.assertEqual(event["date"], expected["date"])
                self.assertEqual(event["venueId"], expected["venue"])
                self.assertEqual(event["artistIds"], expected["artists"])
                self.assertEqual(event["officialUrl"], expected["url"])
                self.assertEqual(event["status"], "confirmed")
                self.assertEqual(event["sourceType"], "salle")
                self.assertIsNone(event["time"])
                self.assertEqual((row["reviewDecision"], row["reviewedBy"], row["reviewedAt"]),
                                 ("approved", "independent-official-verifier", "2026-11-03"))
                proofs = row["officialEvidence"]
                self.assertEqual(len(proofs), 2)
                self.assertEqual(proofs[0]["url"], expected["url"])
                self.assertEqual(proofs[0]["proofType"], "official-organizer-or-venue")
                self.assertEqual((proofs[1]["proofType"], proofs[1]["url"]),
                                 expected["secondary"])
                self.assertTrue(all(p["checkedAt"] == "2026-11-03" for p in proofs))
                self.assertTrue({"artists", "date", "venue"}.issubset(
                    set(proofs[0]["checkedFields"])))

    def test_new_artists_are_consistent_and_not_duplicated(self):
        expected_new = {
            "go-c-20261209-brest-fff-howlin-jaws": ["fff"],
            "go-c-20270402-brest-les-fatals-picards": ["les-fatals-picards"],
            "go-c-20270219-orleans-burning-heads": [],
            "go-c-20270212-rouen-johnny-mafia-les-agamemnonz": ["les-agamemnonz"],
        }
        all_ids = []
        for event_id, expected in expected_new.items():
            new = self.by_id[event_id]["newArtists"]
            self.assertEqual([x["id"] for x in new], expected)
            all_ids.extend(expected)
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_carene_has_exact_two_first_party_proofs(self):
        for event_id in ("go-c-20261209-brest-fff-howlin-jaws",
                         "go-c-20270402-brest-les-fatals-picards"):
            with self.subTest(event=event_id):
                a, b = self.by_id[event_id]["officialEvidence"]
                self.assertTrue({"artists", "date", "venue", "genre", "startTime"}
                                .issubset(set(a["checkedFields"])))
                self.assertTrue({"artists", "date", "venue"}
                                .issubset(set(b["checkedFields"])))


if __name__ == "__main__":
    unittest.main()
