"""Two independent exact time corrections, no rewrite of historic lineups."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
REVIEWED="2026-11-03"
EXPECTED={
 "go-c-20261113-caen-psykup":(
    "https://lecargo.fr/programmation/concert/psykup-7-weeks/","20:00"),
 "go-c-20261121-caen-vulves-assassines":(
    "https://lecargo.fr/programmation/concert/vulves-assassines/","19:30"),
}


class CargoHistoricSignedTests(unittest.TestCase):
    def test_two_and_only_two_corrections_with_official_hour_proofs(self):
        rows=DATA.get("referenceEventTimeCorrections",[])
        self.assertEqual(len(rows),2)
        self.assertEqual({r["eventId"] for r in rows},set(EXPECTED))
        for row in rows:
            with self.subTest(event=row["eventId"]):
                url,doors=EXPECTED[row["eventId"]]
                self.assertEqual(row["reviewDecision"],"approved")
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],REVIEWED)
                self.assertEqual(row["eventPatch"],{
                    "time":"20:30","timeMeaning":"début du concert",
                    "officialUrl":url,"lastVerified":REVIEWED})
                self.assertEqual(len(row["officialEvidence"]),1)
                evidence=row["officialEvidence"][0]
                self.assertEqual(evidence["url"],url)
                self.assertEqual(evidence["proofType"],"official-venue-detail")
                self.assertEqual(evidence["checkedAt"],REVIEWED)
                self.assertTrue({"artists","date","venue","doorTime",
                                 "concertStartTime"}.issubset(set(evidence["checkedFields"])))
                self.assertEqual(evidence["doorTimeConfirmed"],doors)
                self.assertEqual(evidence["concertStartTimeConfirmed"],"20:30")
                self.assertNotIn("artistIds",row["eventPatch"])
                self.assertNotIn("date",row["eventPatch"])
                self.assertNotIn("title",row["eventPatch"])
                self.assertNotIn("venueId",row["eventPatch"])

    def test_previous_approved_queue_and_legacy_proof_preserved(self):
        self.assertEqual(len(DATA["referenceCorrections"]),1)
        self.assertEqual(DATA["referenceCorrections"][0]["eventId"],
                         "go-c-20261212-nantes-lost-in-kyiv")
        self.assertEqual(len(DATA["referenceVenueCorrections"]),10)
        self.assertGreaterEqual(len(DATA["venueApprovals"]), 19)
        ids=[r["event"]["id"] for r in DATA["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn("go-c-20261128-caen-fff-dj-bluff",ids)
        self.assertGreaterEqual(len(ids),120)


if __name__=="__main__":
    unittest.main()
