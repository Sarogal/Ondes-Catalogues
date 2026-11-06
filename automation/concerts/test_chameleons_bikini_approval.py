"""Regressions sur Chameleons + Agonal Gasps, decouverte officielle Bikini."""
import json
import unittest
from pathlib import Path

APPROVED=Path(__file__).with_name("approved.json")
ID="go-c-20261111-toulouse-chameleons"

class ChameleonsApprovalTests(unittest.TestCase):
    def test_official_dated_bill_without_inferred_start(self):
        document=json.loads(APPROVED.read_text(encoding="utf-8"))
        rows=[r for r in document["approvals"] if r["event"]["id"]==ID]
        self.assertEqual(len(rows),1)
        r=rows[0];e=r["event"]
        self.assertEqual(e["title"],"Chameleons + Agonal Gasps")
        self.assertEqual(e["date"],"2026-11-11")
        self.assertEqual(e["venueId"],"le-bikini-toulouse")
        self.assertEqual(e["artistIds"],["chameleons","agonal-gasps"])
        self.assertEqual(e["genres"],["Post-Punk","Rock alternatif"])
        self.assertIsNone(e["time"])
        self.assertEqual(e["officialUrl"],"https://lebikini.com/2026/11/11/chameleons")
        self.assertEqual(r["reviewedBy"],"independent-official-verifier")
        self.assertEqual([a["id"] for a in r["newArtists"]],e["artistIds"])
        self.assertEqual({p["proofType"] for p in r["officialEvidence"]},
                         {"official-organizer-or-venue","first-party-venue-calendar"})
        self.assertTrue(all("startTime" not in p["checkedFields"] for p in r["officialEvidence"]))
        self.assertTrue(all({"artists","date","venue","genre"}.issubset(
                         set(p["checkedFields"])) for p in r["officialEvidence"]))

if __name__=="__main__":
    unittest.main()
