"""Le 106 Rouen: signed same two already-known rock / punk artists."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
ID="go-c-20261121-rouen-death-valley-girls-bella-bizarre"
URL="https://le106.com/agenda/death-valley-girls-bella-bizarre"


class RouenSignedNov2026(unittest.TestCase):
    def test_approved_bill_and_two_separate_exact_first_party_proofs(self):
        rows=[r for r in DATA["approvals"] if r["event"]["id"]==ID]
        self.assertEqual(len(rows),1)
        a=rows[0]; e=a["event"]
        self.assertEqual(a["reviewDecision"],"approved")
        self.assertEqual(a["reviewedBy"],"independent-official-verifier")
        self.assertEqual(a["reviewedAt"],"2026-11-03")
        self.assertEqual((e["title"],e["date"],e["venueId"],e["officialUrl"]),
            ("Death Valley Girls + Bella & the Bizarre","2026-11-21",
             "le-106-rouen",URL))
        self.assertEqual(e["genres"],["Proto-Punk","Garage Punk"])
        self.assertEqual(e["artistIds"],["death-valley-girls","bella-and-the-bizarre"])
        self.assertIsNone(e["time"])
        self.assertEqual(a["newArtists"],[])
        self.assertEqual(len(a["officialEvidence"]),2)
        p,cal=a["officialEvidence"]
        self.assertEqual(p["url"],URL)
        self.assertEqual(p["proofType"],"official-organizer-or-venue")
        self.assertEqual(cal["url"],"https://le106.com/agenda")
        self.assertEqual(cal["proofType"],"first-party-venue-calendar")
        self.assertTrue({"artists","date","venue","genre"}.issubset(p["checkedFields"]))
        self.assertTrue({"artists","date","venue"}.issubset(cal["checkedFields"]))
        self.assertTrue(all(x["checkedAt"]=="2026-11-03" for x in (p,cal)))
        self.assertFalse(any("startTime" in x["checkedFields"] for x in (p,cal)))

    def test_unchanged_previous_approvals_and_signed_time_corrections(self):
        ids=[x["event"]["id"] for x in DATA["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),121)
        self.assertGreaterEqual(len(DATA["venueApprovals"]), 19)
        self.assertEqual(len(DATA["referenceCorrections"]),1)
        self.assertEqual(len(DATA["referenceVenueCorrections"]),10)
        self.assertEqual(len(DATA["referenceEventTimeCorrections"]),2)

if __name__=="__main__":
    unittest.main()
