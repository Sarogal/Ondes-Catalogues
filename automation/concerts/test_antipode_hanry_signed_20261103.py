"""Officially verified Hanry in the Antipode Club; no auto-publication."""
import json
from pathlib import Path
import unittest

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
IDENT="go-c-20261216-rennes-hanry"
URL="https://antipode-rennes.fr/agenda/hanry-2026"

class HanryPrivateSignedTests(unittest.TestCase):
    def test_exact_first_party_le_club_date_genre_artist_and_start(self):
        rows=[x for x in DOC["approvals"] if x["event"]["id"]==IDENT]
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["reviewDecision"],"approved")
        self.assertEqual(row["reviewedBy"],"independent-official-verifier")
        self.assertEqual(row["reviewedAt"],"2026-11-03")
        self.assertEqual(row["event"],{
            "id":IDENT,"title":"Apéro-concert avec Hanry","date":"2026-12-16",
            "time":"19:30","artistIds":["hanry"],"venueId":"antipode-rennes",
            "genres":["Rock"],"status":"confirmed","officialUrl":URL,
            "sourceType":"salle","organizer":"Antipode"})
        self.assertEqual(row["newArtists"],[{"id":"hanry","name":"Hanry"}])
        detail,cal=row["officialEvidence"]
        self.assertEqual(detail["url"],URL)
        self.assertEqual(detail["proofType"],"official-organizer-or-venue")
        self.assertEqual(detail["concertStartTimeConfirmed"],"19:30")
        self.assertEqual(detail["doorTimeConfirmed"],"19:00")
        self.assertFalse(detail["soldOutOnDetailAtReview"])
        self.assertTrue({"artists","date","venue","genre","concertStartTime",
                         "doorTime"}.issubset(detail["checkedFields"]))
        self.assertIn("Le Club",detail["notes"])
        self.assertEqual(cal["url"],"https://antipode-rennes.fr/agenda")
        self.assertEqual(cal["checkedFields"],["artists","date","venue"])
        self.assertNotIn("concertStartTime",cal["checkedFields"])

    def test_previous_134_signatures_are_untouched(self):
        self.assertGreaterEqual(len(DOC["approvals"]),138)
        ids=[x["event"]["id"] for x in DOC["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn("go-c-20270602-rennes-diiv",ids)
        self.assertIn("go-c-20270127-rennes-altin-gun",ids)
        self.assertEqual(len(DOC["referenceVenueCorrections"]),10)

if __name__ == "__main__":
    unittest.main()
