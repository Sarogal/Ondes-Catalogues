"""Four additional Le 106 concerts with named first-party pages and full-year official calendar."""
import json
from pathlib import Path
import unittest

APPROVED=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
EXPECTED={
    "go-c-20270311-rouen-steve-n-seagulls": ("2027-03-11",["steve-n-seagulls"],2,"Rock"),
    "go-c-20270413-rouen-peter-hook-and-the-light": ("2027-04-13",["peter-hook-and-the-light"],2,"Rock"),
    "go-c-20270515-rouen-tagada-jones": ("2027-05-15",["tagada-jones"],2,"Punk Rock"),
    "go-c-20261212-rouen-maustetytot-francis": ("2026-12-12",["maustetytot","francis"],1,"Rock"),
}

class RouenSecondWaveSignedTests(unittest.TestCase):
    def test_four_official_bills_have_matching_proofs_without_inferred_times(self):
        by_id={row["event"]["id"]:row for row in APPROVED["approvals"]}
        for ident,(date,artists,page,genre) in EXPECTED.items():
            with self.subTest(ident=ident):
                row=by_id[ident];ev=row["event"]
                self.assertEqual(row["reviewDecision"],"approved")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],"2026-11-03")
                self.assertEqual((ev["date"],ev["artistIds"],ev["genres"]),(date,artists,[genre]))
                self.assertEqual(ev["venueId"],"le-106-rouen")
                self.assertEqual(ev["status"],"confirmed")
                self.assertIsNone(ev["time"])
                primary,calendar=row["officialEvidence"]
                self.assertEqual(primary["url"],ev["officialUrl"])
                self.assertEqual(primary["proofType"],"official-organizer-or-venue")
                self.assertTrue({"artists","venue","genre"}.issubset(primary["checkedFields"]))
                self.assertNotIn("date",primary["checkedFields"])
                self.assertEqual(calendar["url"],f"https://le106.com/agenda?page={page}")
                self.assertEqual(calendar["proofType"],"first-party-venue-calendar")
                self.assertTrue({"artists","date","venue"}.issubset(calendar["checkedFields"]))
                self.assertNotIn("startTime",calendar["checkedFields"])
                self.assertEqual(primary["checkedAt"],"2026-11-03")
                self.assertEqual(calendar["checkedAt"],"2026-11-03")

    def test_preserves_previous_approvals_and_adds_four_unique_concerts(self):
        rows=APPROVED["approvals"]
        ids=[row["event"]["id"] for row in rows]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(rows),130)
        self.assertGreaterEqual(len(APPROVED["venueApprovals"]), 19)
        self.assertIn("go-c-20270126-rouen-editors-big-sleep",ids)
        self.assertIn("go-c-20270402-herouville-madam",ids)
        new=set(a["id"] for row in rows if row["event"]["id"] in EXPECTED for a in row["newArtists"])
        self.assertEqual(new,{"steve-n-seagulls","peter-hook-and-the-light","maustetytot","francis"})
        self.assertEqual([r["newArtists"] for r in rows if r["event"]["id"]=="go-c-20270515-rouen-tagada-jones"],[[]])

if __name__=="__main__":
    unittest.main()
