"""Cap Caval : identité du bâtiment et concert validés, sans GPS de parking."""
import json
import unittest
from pathlib import Path

APPROVED = Path(__file__).with_name("approved.json")
VENUE = "salle-cap-caval-penmarch"
EVENT = "go-c-20270227-penmarch-howlin-jaws-komodor"

class CapCavalApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc=json.loads(APPROVED.read_text(encoding="utf-8"))
        cls.venue=next(x for x in doc["venueApprovals"] if x["venue"]["id"]==VENUE)
        cls.approval=next(x for x in doc["approvals"] if x["event"]["id"]==EVENT)

    def test_exact_osm_building_and_official_address(self):
        v=self.venue["venue"]
        self.assertEqual((v["city"],v["postalCode"]),("Penmarc’h","29760"))
        self.assertEqual(v["address"],"Avenue de Skibbereen")
        self.assertEqual((v["latitude"],v["longitude"]),(47.81333,-4.33766))
        self.assertEqual(v["geoSource"],"https://mapcarta.com/W66608817")
        self.assertEqual([p["proofType"] for p in self.venue["officialEvidence"]],
                         ["official-venue-address","openstreetmap-venue-way"])
        self.assertIn("pas son entrée",v["geoPrecision"])
        self.assertNotIn("N5752074999",v["geoSource"])

    def test_official_event_and_support_roles_separately(self):
        e=self.approval["event"]
        self.assertEqual(e["date"],"2027-02-27")
        self.assertEqual(e["venueId"],VENUE)
        self.assertEqual(e["artistIds"],["howlin-jaws","komodor"])
        self.assertIsNone(e["time"])
        self.assertEqual(e["genres"],["Psych Rock","Hard Rock"])
        self.assertEqual(self.approval["newArtists"],[])
        self.assertEqual(self.approval["reviewedBy"],"independent-official-verifier")
        first,second=self.approval["officialEvidence"]
        self.assertEqual(first["url"],e["officialUrl"])
        self.assertEqual(first["proofType"],"official-organizer-or-venue")
        self.assertEqual(second["url"],"https://radical-production.fr/artistes/howlin-jaws/")
        self.assertIn("supportRole",second["checkedFields"])
        self.assertNotIn("concertStartTime",first["checkedFields"])

    def test_no_festival_or_inferred_location(self):
        a=self.approval
        self.assertEqual(a["reviewDecision"],"approved")
        self.assertEqual(a["event"]["sourceType"],"salle")
        self.assertFalse(any("festival" in g.lower() for g in a["event"]["genres"]))
        self.assertEqual(a["reviewedAt"],"2026-11-05")

if __name__=="__main__":
    unittest.main()
