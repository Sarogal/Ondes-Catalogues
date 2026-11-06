"""Signatures privées Le Cargö: date, artistes et séparation portes/début."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
DATA=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
ID="go-c-20261128-caen-fff-dj-bluff"
URL="https://lecargo.fr/programmation/concert/fff/"


class CargoSignedTests(unittest.TestCase):
    def test_only_exact_fff_dj_bluff_nominative_approval(self):
        rows=[x for x in DATA["approvals"] if x["event"]["id"]==ID]
        self.assertEqual(len(rows),1)
        x=rows[0];event=x["event"]
        self.assertEqual(x["reviewDecision"],"approved")
        self.assertEqual(x["reviewedBy"],"independent-official-verifier")
        self.assertEqual(x["reviewedAt"],"2026-11-03")
        self.assertEqual(event["title"],"FFF + DJ Bluff")
        self.assertEqual(event["date"],"2026-11-28")
        self.assertEqual(event["time"],"20:30")
        self.assertEqual(event["venueId"],"le-cargo-caen")
        self.assertEqual(event["officialUrl"],URL)
        self.assertEqual(event["artistIds"],["fff","dj-bluff"])
        self.assertEqual(event["genres"],["Funk Rock"])
        self.assertEqual(event["sourceType"],"salle")
        self.assertEqual(x["newArtists"],[{"id":"dj-bluff","name":"DJ Bluff"}])
        self.assertEqual(len(x["officialEvidence"]),1)
        proof=x["officialEvidence"][0]
        self.assertEqual(proof["url"],URL)
        self.assertEqual(proof["checkedAt"],"2026-11-03")
        self.assertEqual(proof["proofType"],"official-organizer-or-venue")
        self.assertTrue({"artists","date","venue","genre",
                         "doorTime","concertStartTime"}.issubset(
                              set(proof["checkedFields"])))
        self.assertEqual(proof["doorTimeConfirmed"],"19:30")
        self.assertEqual(proof["concertStartTimeConfirmed"],"20:30")

    def test_original_approvals_preserved_and_no_same_venue_fff_same_day(self):
        ids=[x["event"]["id"] for x in DATA["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),120)
        clashes=[x for x in DATA["approvals"]
                 if x["event"]["date"]=="2026-11-28"
                 and x["event"]["venueId"]=="le-cargo-caen"
                 and "fff" in x["event"]["artistIds"]]
        self.assertEqual(len(clashes),1)


if __name__=="__main__":
    unittest.main()
