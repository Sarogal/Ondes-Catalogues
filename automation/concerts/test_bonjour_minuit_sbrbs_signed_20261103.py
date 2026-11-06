"""Exact signed 2027 SBRBS rock release party, no invented musical start."""
import json
from pathlib import Path
import unittest

DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
IDENT="go-c-20270130-saint-brieuc-sbrbs"
URL="https://bonjour-minuit.fr/evenement/sbrbs-30janv27/"
ARTISTS=["sbrbs","atoem","sarakiniko","dj-cup-of-tea"]
NAMES=["SBRBS","Atoem","Sarakiniko","DJ Cup of Tea"]

class SbrbsPrivateApprovalTests(unittest.TestCase):
    def test_exact_named_bill_independent_source_and_four_unique_artists(self):
        rows=[r for r in DOC["approvals"] if r["event"]["id"]==IDENT]
        self.assertEqual(len(rows),1)
        a=rows[0];e=a["event"]
        self.assertEqual((a["reviewDecision"],a["reviewedBy"],a["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-03"))
        self.assertEqual(e,{
            "id":IDENT,"title":"SBRBS + Atoem + Sarakiniko + DJ Cup of Tea",
            "date":"2027-01-30","time":None,"artistIds":ARTISTS,
            "venueId":"bonjour-minuit-saint-brieuc",
            "genres":["Rock indépendant"],"status":"confirmed",
            "officialUrl":URL,"sourceType":"salle"})
        self.assertEqual(a["newArtists"],[
            {"id":aid,"name":name} for aid,name in zip(ARTISTS,NAMES)])
        self.assertEqual([x["url"] for x in a["officialEvidence"]],
                         [URL,"https://bonjour-minuit.fr/agenda/"])
        self.assertEqual([x["proofType"] for x in a["officialEvidence"]],
                         ["official-organizer-or-venue","first-party-venue-calendar"])
        self.assertTrue({"artists","date","venue","genre"}.issubset(
            a["officialEvidence"][0]["checkedFields"]))
        self.assertNotIn("concertStartTime",a["officialEvidence"][0]["checkedFields"])
        self.assertNotIn("startTime",a["officialEvidence"][1]["checkedFields"])
        self.assertIn("20h30",a["officialEvidence"][0]["notes"])

    def test_older_magma_hanry_and_all_identifiers_preserved(self):
        self.assertGreaterEqual(len(DOC["approvals"]),138)
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        ids=[x["event"]["id"] for x in DOC["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        for id_ in ("go-c-20261202-saint-brieuc-magma",
                    "go-c-20261216-rennes-hanry",
                    "go-c-20270602-rennes-diiv"):
            self.assertIn(id_,ids)

if __name__=="__main__":
    unittest.main()
