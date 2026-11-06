"""Preuves nominatives des concerts Le Bikini ; aucune heure de portes inférée."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit


EXPECTED = {
    "go-c-20261113-toulouse-tagada-jones": (
        "2026-11-13",
        ["tagada-jones", "les-tambours-du-bronx"],
        "https://lebikini.com/2026/11/13/tagada-jones-les-tambours-du-bronx",
        []),
    "go-c-20261114-toulouse-beast-in-black": (
        "2026-11-14",
        ["beast-in-black", "sonata-arctica", "frozen-crown"],
        "https://lebikini.com/2026/11/14/beast-in-black-sonata-arctica-frozen-crown",
        ["beast-in-black", "sonata-arctica", "frozen-crown"]),
    "go-c-20261117-toulouse-slift": (
        "2026-11-17",
        ["slift", "heeka"],
        "https://lebikini.com/2026/11/17/slift",
        ["heeka"]),
    "go-c-20261125-toulouse-marillion": (
        "2026-11-25", ["marillion"],
        "https://lebikini.com/2026/11/25/marillion",
        ["marillion"]),
    "go-c-20261126-toulouse-the-stranglers": (
        "2026-11-26", ["the-stranglers"],
        "https://lebikini.com/2026/11/26/the-stranglers",
        ["the-stranglers"]),
    "go-c-20261129-toulouse-accept": (
        "2026-11-29", ["accept", "dynazty", "enforcer"],
        "https://lebikini.com/2026/11/29/accept-50th-anniversary-tour-dynazty-tailgunner",
        []),
}


class BikiniApprovedEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = Path(__file__).with_name("approved.json")
        approvals = json.loads(p.read_text(encoding="utf-8"))
        cls.rows = {row["event"]["id"]: row for row in approvals["approvals"]}

    def test_six_individually_verified_events_no_doors_time(self):
        for identifier, (date, artists, url, fresh) in EXPECTED.items():
            with self.subTest(identifier=identifier):
                row = self.rows[identifier]
                event = row["event"]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], "2026-11-03")
                self.assertEqual(event["date"], date)
                self.assertEqual(event["artistIds"], artists)
                self.assertEqual(event["venueId"], "le-bikini-toulouse")
                self.assertEqual(event["officialUrl"], url)
                self.assertIsNone(event["time"])
                self.assertEqual([a["id"] for a in row["newArtists"]], fresh)
                self.assertEqual(event["sourceType"], "salle")
                self.assertEqual(event["status"], "confirmed")
                self.assertEqual(len(row["officialEvidence"]), 2)
                proofs = row["officialEvidence"]
                self.assertEqual(proofs[0]["url"], url)
                self.assertEqual(proofs[0]["proofType"], "official-organizer-or-venue")
                self.assertEqual(proofs[1]["url"],
                    "https://lebikini.com/programmation/-/concert")
                self.assertEqual(proofs[1]["proofType"], "first-party-venue-calendar")
                for proof in proofs:
                    self.assertEqual(proof["checkedAt"], "2026-11-03")
                    self.assertTrue({"artists", "date", "venue", "genre"}.issubset(
                        set(proof["checkedFields"])))
                    self.assertNotIn("startTime", proof["checkedFields"])
                    self.assertEqual(urlsplit(proof["url"]).hostname, "lebikini.com")


if __name__ == "__main__":
    unittest.main()
