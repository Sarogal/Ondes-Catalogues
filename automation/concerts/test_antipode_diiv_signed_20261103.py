"""2027 DIIV Antipode verified event, named time/door and no invented support."""
import json
from pathlib import Path
import unittest

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
IDENT="go-c-20270602-rennes-diiv"
URL="https://antipode-rennes.fr/agenda/diiv-2027"

class DiivPrivateSignedTests(unittest.TestCase):
    def test_single_exact_approved_official_diiv_billed_without_support(self):
        rows=[r for r in DOC["approvals"] if r["event"]["id"]==IDENT]
        self.assertEqual(len(rows),1)
        row=rows[0]
        ev=row["event"]
        self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-03"))
        self.assertEqual(ev,{
            "id":IDENT,"title":"DIIV","date":"2027-06-02","time":"20:30",
            "artistIds":["diiv"],"venueId":"antipode-rennes",
            "genres":["Rock"],"status":"confirmed","officialUrl":URL,
            "sourceType":"salle"})
        self.assertEqual(row["newArtists"],[{"id":"diiv","name":"DIIV"}])
        first,cal=row["officialEvidence"]
        self.assertEqual(first["url"],URL)
        self.assertEqual(first["proofType"],"official-organizer-or-venue")
        self.assertEqual(first["concertStartTimeConfirmed"],"20:30")
        self.assertEqual(first["doorTimeConfirmed"],"20:00")
        self.assertIs(first["soldOutOnDetailAtReview"],False)
        self.assertEqual(cal["url"],"https://antipode-rennes.fr/agenda")
        self.assertEqual(cal["proofType"],"first-party-venue-calendar")
        self.assertTrue({"artists","date","venue"}.issubset(cal["checkedFields"]))
        self.assertTrue({"artists","date","venue","genre","doorTime",
                         "concertStartTime"}.issubset(first["checkedFields"]))
        self.assertEqual(first["checkedAt"],"2026-11-03")
        self.assertEqual(cal["checkedAt"],"2026-11-03")

    def test_previous_ids_and_location_correction_preserved(self):
        self.assertGreaterEqual(len(DOC["approvals"]),138)
        self.assertEqual(len({x["event"]["id"] for x in DOC["approvals"]}),len(DOC["approvals"]))
        self.assertEqual(len(DOC["referenceVenueCorrections"]),10)
        self.assertIn("go-c-20261212-rennes-girls-in-hawaii-chaton-laveur",
                      {x["event"]["id"] for x in DOC["approvals"]})
        self.assertIn("antipode-rennes",
                      {x["venueId"] for x in DOC["referenceVenueCorrections"]})

if __name__=="__main__":
    unittest.main()
