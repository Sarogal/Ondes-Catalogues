"""Contrôle des sept nouvelles signatures exactes, sans candidat brut ni pseudo-artiste."""
import json
import unittest
from pathlib import Path

DOC = json.loads((Path(__file__).resolve().parent / "approved.json").read_text(encoding="utf-8"))
SPECS = {
    "go-c-20270114-wasquehal-rhapsody-of-fire": ("2027-01-14", "the-black-lab-wasquehal", 5, None, []),
    "go-c-20270206-wasquehal-revnoir": ("2027-02-06", "the-black-lab-wasquehal", 2, None, []),
    "go-c-20270115-biarritz-svinkels": ("2027-01-15", "atabal-biarritz", 2, None, ["svinkels", "voizins-vigilants"]),
    "go-c-20261126-blois-carmen-sea": ("2026-11-26", "le-chatodo-blois", 1, "19:30", ["carmen-sea"]),
    "go-c-20261111-strasbourg-mogwai": ("2026-11-11", "la-laiterie-strasbourg", 2, "20:00", ["mogwai", "forest-swords"]),
    "go-c-20261127-paris-lugosi": ("2026-11-27", "glazart-paris", 3, None, ["lugosi", "l-idylle", "chiennes"]),
    "go-c-20270209-paris-melrose-avenue": ("2027-02-09", "le-trabendo-paris", 1, None, ["melrose-avenue"]),
}

class NewSevenOfficialApprovalTests(unittest.TestCase):
    def test_all_seven_exact_signatures(self):
        rows = {x["event"]["id"]: x for x in DOC["approvals"]}
        self.assertEqual(len(rows), len(DOC["approvals"]))
        self.assertGreaterEqual(len(rows), 149)
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        for ident, (date, venue, n, t, added) in SPECS.items():
            with self.subTest(ident=ident):
                row = rows[ident]
                e = row["event"]
                self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                    ("approved","independent-official-verifier","2026-11-04"))
                self.assertEqual(e["date"], date)
                self.assertEqual(e["venueId"], venue)
                self.assertEqual(e["status"], "confirmed")
                self.assertEqual(e["sourceType"], "salle")
                self.assertEqual(e["time"], t)
                self.assertEqual(len(e["artistIds"]), n)
                self.assertEqual(len(set(e["artistIds"])), n)
                self.assertEqual([a["id"] for a in row["newArtists"]], added)
                p = row["officialEvidence"][0]
                self.assertEqual(p["url"], e["officialUrl"])
                self.assertEqual(p["proofType"], "official-organizer-or-venue")
                self.assertEqual(p["checkedAt"], "2026-11-04")
                self.assertTrue({"artists","date","venue","genre"} <= set(p["checkedFields"]))
                if t is None:
                    self.assertNotIn("concertStartTime", p["checkedFields"])
                if len(row["officialEvidence"]) == 2:
                    self.assertEqual(row["officialEvidence"][1]["proofType"],
                                     "first-party-venue-calendar")

    def test_previous_signatures_are_untouched_and_no_uncertain_guests(self):
        rows = {r["event"]["id"]: r for r in DOC["approvals"]}
        for ident in ("go-c-20270220-nantes-hipskor",
                      "go-c-20270408-nantes-antimatter",
                      "go-c-20261205-toulouse-changeline",
                      "go-c-20270307-toulouse-mol",
                      "go-c-20261107-rennes-excellento",
                      "go-c-20261202-saint-brieuc-magma"):
            self.assertIn(ident, rows)
        self.assertEqual(rows["go-c-20270115-biarritz-svinkels"]["event"]["artistIds"],
                         ["svinkels","voizins-vigilants"])
        self.assertEqual(rows["go-c-20270114-wasquehal-rhapsody-of-fire"]["newArtists"], [])

if __name__ == "__main__":
    unittest.main()
