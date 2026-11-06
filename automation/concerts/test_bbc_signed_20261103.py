"""BBC approved source-specific dates; no implied 20:00 musical starts."""
import json
from pathlib import Path
import unittest

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(
    encoding="utf-8"))
SIGNED={
 "go-c-20270205-herouville-ugly-kid-joe":{
     "name":"Ugly Kid Joe","date":"2027-02-05",
     "url":"https://bigbandcafe.com/ugly-kid-joe/",
     "ticket":"https://billetterie.bigbandcafe.com/agenda/118-UGLY-KID-JOE?session=118",
     "artists":["ugly-kid-joe"],"genres":["Hard Rock"],"new":[]},
 "go-c-20270402-herouville-madam":{
     "name":"MADAM","date":"2027-04-02",
     "url":"https://bigbandcafe.com/madam/",
     "ticket":"https://billetterie.bigbandcafe.com/agenda/121-MADAM?session=121",
     "artists":["madam"],"genres":["Rock"],
     "new":[{"id":"madam","name":"MADAM"}]}
}


class BBCPrivateApprovalsTests(unittest.TestCase):
    def test_exact_official_two_source_signed_records(self):
        rows={x["event"]["id"]:x for x in DOC["approvals"]}
        for ident,spec in SIGNED.items():
            with self.subTest(ident=ident):
                self.assertIn(ident,rows)
                r=rows[ident]
                e=r["event"]
                self.assertEqual(r["reviewDecision"],"approved")
                self.assertEqual(r["reviewedBy"],"independent-official-verifier")
                self.assertEqual(r["reviewedAt"],"2026-11-03")
                self.assertEqual((e["title"],e["date"],e["artistIds"],
                                  e["genres"],e["officialUrl"],e["venueId"]),
                    (spec["name"],spec["date"],spec["artists"],spec["genres"],
                     spec["url"],"big-band-cafe-herouville"))
                self.assertIsNone(e["time"])
                self.assertEqual(r["newArtists"],spec["new"])
                self.assertEqual(len(r["officialEvidence"]),2)
                for proof,url,kind,fields in zip(
                    r["officialEvidence"],(spec["url"],spec["ticket"]),
                    ("official-organizer-or-venue",
                     "authorized-ticket-distributor-full-date"),
                    ({"artists","date","venue","genre"},
                     {"artists","date","venue"})):
                    self.assertEqual(proof["url"],url)
                    self.assertEqual(proof["proofType"],kind)
                    self.assertEqual(proof["checkedAt"],"2026-11-03")
                    self.assertTrue(fields.issubset(proof["checkedFields"]))
                    self.assertFalse("startTime" in proof["checkedFields"])

    def test_older_approvals_and_cargo_corrections_remain_intact(self):
        self.assertEqual(len(DOC["approvals"]),len({
            r["event"]["id"] for r in DOC["approvals"]}))
        self.assertGreaterEqual(len(DOC["approvals"]),123)
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        self.assertEqual(len(DOC["referenceCorrections"]),1)
        self.assertEqual(len(DOC["referenceVenueCorrections"]),10)
        self.assertEqual(len(DOC["referenceEventTimeCorrections"]),2)


if __name__=="__main__":
    unittest.main()
