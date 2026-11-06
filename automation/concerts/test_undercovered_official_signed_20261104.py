"""Ten exact first-party concert reviews, including protected music-start times."""
import json
import unittest
from pathlib import Path

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
SPECS={
    "go-c-20261120-saint-etienne-inspector-cluzo":("2026-11-20","le-fil-saint-etienne","20:30",["the-inspector-cluzo","grant-haua"],["grant-haua"]),
    "go-c-20261211-saint-etienne-guadal-tejaz":("2026-12-11","le-fil-saint-etienne","20:30",["guadal-tejaz","111"],["guadal-tejaz","111"]),
    "go-c-20270129-saint-etienne-skip-the-use":("2027-01-29","le-fil-saint-etienne","20:30",["skip-the-use","imparfait"],["imparfait"]),
    "go-c-20270130-saint-etienne-ultra-vomit":("2027-01-30","le-fil-saint-etienne","20:30",["ultra-vomit"],["ultra-vomit"]),
    "go-c-20270227-saint-etienne-vulves-assassines":("2027-02-27","le-fil-saint-etienne","20:30",["vulves-assassines"],[]),
    "go-c-20270401-saint-etienne-howlin-jaws":("2027-04-01","le-fil-saint-etienne","20:30",["howlin-jaws"],[]),
    "go-c-20261118-nimes-fff":("2026-11-18","paloma-nimes",None,["fff","bleu-satellite"],["bleu-satellite"]),
    "go-c-20261124-nimes-marillion":("2026-11-24","paloma-nimes",None,["marillion","lazuli"],["lazuli"]),
    "go-c-20270312-nimes-skip-the-use":("2027-03-12","paloma-nimes",None,["skip-the-use","supreme-nightclub"],[]),
    "go-c-20261204-tarbes-inspector-cluzo":("2026-12-04","la-gespe-tarbes",None,["the-inspector-cluzo"],[]),
}

class SignedUndercoveredRegionTests(unittest.TestCase):
    def test_all_ten_independent_review_signatures_unique(self):
        rows={r["event"]["id"]:r for r in DOC["approvals"]}
        self.assertEqual(len(rows),len(DOC["approvals"]))
        self.assertGreaterEqual(len(rows),159)
        for ident,(date,venue,time,artists,new) in SPECS.items():
            with self.subTest(ident=ident):
                row=rows[ident]
                evt=row["event"]
                self.assertEqual(row["reviewDecision"],"approved")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],"2026-11-04")
                self.assertEqual((evt["date"],evt["venueId"],evt["time"]),(date,venue,time))
                self.assertEqual(evt["artistIds"],artists)
                self.assertEqual([a["id"] for a in row["newArtists"]],new)
                self.assertEqual(evt["status"],"confirmed")
                self.assertEqual(evt["sourceType"],"salle")
                proof,calendar=row["officialEvidence"]
                self.assertEqual(proof["url"],evt["officialUrl"])
                self.assertEqual(proof["proofType"],"official-organizer-or-venue")
                self.assertEqual(calendar["proofType"],"first-party-venue-calendar")
                self.assertEqual(proof["checkedAt"],"2026-11-04")
                self.assertTrue({"artists","date","venue","genre"} <= set(proof["checkedFields"]))
                self.assertEqual("concertStartTime" in proof["checkedFields"],time is not None)
                self.assertNotIn("concertStartTime",calendar["checkedFields"])
                self.assertIn(evt["venueId"],("le-fil-saint-etienne","paloma-nimes","la-gespe-tarbes"))

    def test_published_history_retained_and_no_unverified_support_names(self):
        rows={r["event"]["id"]:r for r in DOC["approvals"]}
        for ident in ("go-c-20270114-wasquehal-rhapsody-of-fire",
                      "go-c-20270209-paris-melrose-avenue",
                      "go-c-20261126-blois-carmen-sea",
                      "go-c-20270408-nantes-antimatter"):
            self.assertIn(ident,rows)
        for ident in ("go-c-20270130-saint-etienne-ultra-vomit",
                      "go-c-20270227-saint-etienne-vulves-assassines"):
            self.assertEqual(len(rows[ident]["event"]["artistIds"]),1)
            self.assertNotIn("guest",rows[ident]["event"]["artistIds"])
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)

if __name__=="__main__":
    unittest.main()
