"""Signed first Saint-Brieuc concert and independent location proof."""
import json
from pathlib import Path
import unittest

APP=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
ID="go-c-20261202-saint-brieuc-magma"
URL="https://bonjour-minuit.fr/evenement/magma-02dec26/"
GEO="https://acceslibre.beta.gouv.fr/app/22-saint-brieuc/a/salle-de-spectacle/erp/bonjour-minuit/"

class BonjourMinuitSignedTests(unittest.TestCase):
    def test_exact_event_and_no_artificial_musical_start(self):
        rows=[row for row in APP["approvals"] if row["event"]["id"]==ID]
        self.assertEqual(len(rows),1)
        item=rows[0]
        self.assertEqual(item["reviewDecision"],"approved")
        self.assertEqual(item["reviewedBy"],"independent-official-verifier")
        self.assertEqual(item["reviewedAt"],"2026-11-03")
        self.assertEqual(item["event"],{
            "id":ID,"title":"Magma","date":"2026-12-02",
            "time":None,"artistIds":["magma"],
            "venueId":"bonjour-minuit-saint-brieuc",
            "genres":["Rock progressif"],"status":"confirmed",
            "officialUrl":URL,"sourceType":"salle"})
        self.assertEqual(item["newArtists"],[])
        detail,agenda=item["officialEvidence"]
        self.assertEqual(detail["url"],URL)
        self.assertEqual(agenda["url"],"https://bonjour-minuit.fr/agenda/")
        self.assertTrue({"artists","date","venue","genre"}.issubset(detail["checkedFields"]))
        self.assertFalse({"concertStartTime","doorTime","startTime"} &
                         set(detail["checkedFields"]))
        self.assertIn("indicatif",detail["notes"])

    def test_venue_exact_government_point_no_entrance_claim(self):
        venues=[x for x in APP["venueApprovals"] if
                x["venue"]["id"]=="bonjour-minuit-saint-brieuc"]
        self.assertEqual(len(venues),1)
        row=venues[0]
        self.assertEqual(row["reviewDecision"],"approved")
        self.assertEqual(row["reviewedBy"],"independent-official-verifier")
        venue=row["venue"]
        self.assertEqual((venue["city"],venue["postalCode"],venue["department"]),
                         ("Saint-Brieuc","22000","22"))
        self.assertEqual((venue["latitude"],venue["longitude"]),(48.5196,-2.7852))
        self.assertEqual(venue["geoSource"],GEO)
        self.assertIn("non assimilées",venue["geoPrecision"])
        self.assertEqual(row["officialEvidence"][0]["url"],
                         "https://bonjour-minuit.fr/contact/")
        self.assertEqual(row["officialEvidence"][1]["url"],GEO)

    def test_preserve_all_prior_event_ids_and_venues(self):
        self.assertGreaterEqual(len(APP["approvals"]),138)
        self.assertGreaterEqual(len(APP["venueApprovals"]), 19)
        ids=[r["event"]["id"] for r in APP["approvals"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn("go-c-20261216-rennes-hanry",ids)
        self.assertIn("go-c-20270602-rennes-diiv",ids)

if __name__=="__main__":
    unittest.main()
