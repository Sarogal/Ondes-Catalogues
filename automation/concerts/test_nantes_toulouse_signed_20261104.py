"""Lot officiel Nantes/Toulouse du 04/11/2026 : quatre dates, sans fusion de candidats bruts."""
import json
from pathlib import Path
import unittest

APP = json.loads((Path(__file__).resolve().parent / "approved.json").read_text(encoding="utf-8"))
SIGNED = {
    "go-c-20270220-nantes-hipskor": (
        "2027-02-20", "Hipskör + Lifeboats + Polybius",
        "le-ferrailleur-nantes", ["hipskor", "lifeboats", "polybius"],
        "https://www.leferrailleur.fr/evenement/hipskor-lifeboats-polybius/5375",
        "20:30", ["hipskor", "polybius"]
    ),
    "go-c-20270408-nantes-antimatter": (
        "2027-04-08", "Antimatter", "le-ferrailleur-nantes",
        ["antimatter"], "https://www.leferrailleur.fr/evenement/antimatter/5404",
        "20:30", ["antimatter"]
    ),
    "go-c-20261205-toulouse-changeline": (
        "2026-12-05", "Changeline", "le-rex-toulouse",
        ["changeline"], "https://www.lerextoulouse.com/fr/programmation/changeline/",
        None, ["changeline"]
    ),
    "go-c-20270307-toulouse-mol": (
        "2027-03-07", "MØL & Guest", "le-rex-toulouse",
        ["m-l"], "https://www.lerextoulouse.com/fr/programmation/mol-et-guest/",
        None, []
    )
}

class NantesToulouseSignedTests(unittest.TestCase):
    def test_four_specific_approved_official_gigs(self):
        entries = {item["event"]["id"]: item for item in APP["approvals"]}
        self.assertEqual(len(entries), len(APP["approvals"]))
        self.assertGreaterEqual(len(entries), 142)
        for ident, (date, title, venue, artists, url, start, new_ids) in SIGNED.items():
            with self.subTest(event=ident):
                row = entries[ident]
                event = row["event"]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], "2026-11-04")
                self.assertEqual(event["date"], date)
                self.assertEqual(event["title"], title)
                self.assertEqual(event["venueId"], venue)
                self.assertEqual(event["artistIds"], artists)
                self.assertEqual(event["officialUrl"], url)
                self.assertEqual(event["time"], start)
                self.assertEqual(event["sourceType"], "salle")
                self.assertEqual(event["status"], "confirmed")
                self.assertEqual([a["id"] for a in row["newArtists"]], new_ids)
                self.assertEqual(len(row["officialEvidence"]), 1)
                proof = row["officialEvidence"][0]
                self.assertEqual(proof["url"], url)
                self.assertEqual(proof["proofType"], "official-organizer-or-venue")
                self.assertEqual(proof["checkedAt"], "2026-11-04")
                self.assertTrue({"artists", "date", "venue", "genre"} <= set(proof["checkedFields"]))
                if venue == "le-rex-toulouse":
                    self.assertIsNone(event["time"])
                    self.assertNotIn("concertStartTime", proof["checkedFields"])
                else:
                    self.assertIn("concertStartTime", proof["checkedFields"])

    def test_preserve_earlier_approved_gigs_and_avoid_guest_inference(self):
        rows = {e["event"]["id"]: e for e in APP["approvals"]}
        for prior in ("go-c-20261107-rennes-excellento",
                      "go-c-20261202-saint-brieuc-magma",
                      "go-c-20270130-saint-brieuc-sbrbs"):
            self.assertIn(prior, rows)
        mol = rows["go-c-20270307-toulouse-mol"]
        self.assertEqual(mol["event"]["artistIds"], ["m-l"])
        self.assertEqual(mol["newArtists"], [])
        self.assertGreaterEqual(len(APP["venueApprovals"]), 19)

if __name__ == "__main__":
    unittest.main()
