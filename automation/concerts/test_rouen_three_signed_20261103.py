"""Three Le 106 rock bills: dates proven by the calendar, not detail pages."""
import json
from pathlib import Path
import unittest

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(
    encoding="utf-8"))
CAL="https://le106.com/agenda?page=1"
FIXTURES={
"go-c-20261210-rouen-the-sheepdogs-steve-hill":
 ("2026-12-10","The Sheepdogs + Steve Hill",["the-sheepdogs","steve-hill"],
  ["The Sheepdogs","Steve Hill"],"https://le106.com/agenda/sheepdogs",False),
"go-c-20270121-rouen-skip-the-use-mdns":
 ("2027-01-21","Skip The Use + MDNS",["skip-the-use","mdns"],
  ["Skip The Use","MDNS"],"https://le106.com/agenda/skip-use",True),
"go-c-20270126-rouen-editors-big-sleep":
 ("2027-01-26","Editors + Big Sleep",["editors","big-sleep"],
  ["Editors","Big Sleep"],"https://le106.com/agenda/editors",True),
}


class RouenThreeSignedTests(unittest.TestCase):
    def test_exact_date_artist_venue_and_evidence_per_field(self):
        d={r["event"]["id"]:r for r in DOC["approvals"]}
        for ident,(date,title,ids,names,url,sold) in FIXTURES.items():
            with self.subTest(id=ident):
                r=d[ident];e=r["event"]
                self.assertEqual(r["reviewDecision"],"approved")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["reviewedAt"],"2026-11-03")
                self.assertEqual(e["date"],date)
                self.assertEqual(e["title"],title)
                self.assertEqual(e["artistIds"],ids)
                self.assertEqual(e["genres"],["Rock"])
                self.assertEqual(e["venueId"],"le-106-rouen")
                self.assertEqual(e["officialUrl"],url)
                self.assertIsNone(e["time"])
                self.assertEqual(r["newArtists"],
                    [{"id":a,"name":n} for a,n in zip(ids,names)])
                self.assertEqual(len(r["officialEvidence"]),2)
                p,calendar=r["officialEvidence"]
                self.assertEqual(p["url"],url)
                self.assertEqual(p["proofType"],"official-organizer-or-venue")
                self.assertTrue({"artists","venue","genre"}.issubset(p["checkedFields"]))
                self.assertNotIn("date",p["checkedFields"])
                self.assertNotIn("startTime",p["checkedFields"])
                self.assertEqual(calendar["url"],CAL)
                self.assertEqual(calendar["proofType"],"first-party-venue-calendar")
                self.assertTrue({"artists","date","venue"}.issubset(
                    calendar["checkedFields"]))
                self.assertNotIn("startTime",calendar["checkedFields"])
                self.assertEqual(calendar["soldOutOnCalendarAtReview"],sold)
                self.assertEqual(p["checkedAt"],"2026-11-03")
                self.assertEqual(calendar["checkedAt"],"2026-11-03")

    def test_six_distinct_new_artists_and_all_older_approvals_preserved(self):
        ids=[r["event"]["id"] for r in DOC["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),126)
        names=[aid for key in FIXTURES for aid in FIXTURES[key][2]]
        self.assertEqual(len(set(names)),6)
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        self.assertEqual(len(DOC["referenceCorrections"]),1)
        self.assertEqual(len(DOC["referenceVenueCorrections"]),10)
        self.assertEqual(len(DOC["referenceEventTimeCorrections"]),2)
        self.assertIn("go-c-20270402-herouville-madam",ids)


if __name__=="__main__":
    unittest.main()
