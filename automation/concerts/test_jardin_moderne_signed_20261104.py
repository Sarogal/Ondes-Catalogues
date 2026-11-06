"""Le Jardin Moderne Rennes: signed exact date, venue, artists and geo."""
import json
from pathlib import Path
import unittest
DOC=json.loads((Path(__file__).resolve().parent/"approved.json").read_text(encoding="utf-8"))
IDENT="go-c-20261107-rennes-excellento"
VENUE="le-jardin-moderne-rennes"
URL="https://www.jardinmoderne.org/agenda/excellento-joey-gluten-batarde/"
GEO="https://mapcarta.com/fr/W80301709"
BANDS=["excellento","joey-gluten","batarde"]
NAMES=["Excellento","Joey Glüten","Bâtarde"]

class JardinModerneSignedTests(unittest.TestCase):
    def test_signatures_source_date_artists_no_stage_time(self):
        rows=[r for r in DOC["approvals"] if r["event"]["id"]==IDENT]
        self.assertEqual(len(rows),1)
        row=rows[0]
        ev=row["event"]
        self.assertEqual((row["reviewDecision"],row["reviewedBy"],row["reviewedAt"]),
                         ("approved","independent-official-verifier","2026-11-03"))
        self.assertEqual(ev["title"],"Excellento + Joey Glüten + Bâtarde")
        self.assertEqual(ev["date"],"2026-11-07")
        self.assertIsNone(ev["time"])
        self.assertEqual(ev["artistIds"],BANDS)
        self.assertEqual(ev["venueId"],VENUE)
        self.assertEqual(ev["genres"],["Rock"])
        self.assertEqual(ev["officialUrl"],URL)
        self.assertEqual(ev["status"],"confirmed")
        self.assertEqual(ev["sourceType"],"salle")
        self.assertEqual(row["newArtists"],[
             {"id":ident,"name":name} for ident,name in zip(BANDS,NAMES)])
        self.assertEqual([p["url"] for p in row["officialEvidence"]],
            [URL,"https://www.jardinmoderne.org/agenda/"])
        self.assertEqual([p["proofType"] for p in row["officialEvidence"]],
            ["official-organizer-or-venue","first-party-venue-calendar"])
        for proof in row["officialEvidence"]:
            self.assertEqual(proof["checkedAt"],"2026-11-03")
            self.assertFalse({"concertStartTime","startTime","doorTime"} &
                             set(proof["checkedFields"]))

    def test_exact_independent_position_and_address(self):
        rows=[r for r in DOC["venueApprovals"] if r["venue"]["id"]==VENUE]
        self.assertEqual(len(rows),1)
        row=rows[0]
        v=row["venue"]
        self.assertEqual(v["address"],"11 rue du Manoir de Servigné")
        self.assertEqual(v["postalCode"],"35000")
        self.assertEqual(v["city"],"Rennes")
        self.assertEqual((v["latitude"],v["longitude"]),(48.10164,-1.72557))
        self.assertIn("non assimilé à l'entrée",v["geoPrecision"])
        self.assertEqual(v["geoSource"],GEO)
        self.assertEqual([p["url"] for p in row["officialEvidence"]],
                         ["https://www.jardinmoderne.org/acces-2/",GEO])
        self.assertEqual([p["proofType"] for p in row["officialEvidence"]],
                         ["official-venue-address","openstreetmap-venue-way"])

    def test_no_deletion_duplicate_or_overwrite_previous_approvals(self):
        ids=[x["event"]["id"] for x in DOC["approvals"]]
        venues=[x["venue"]["id"] for x in DOC["venueApprovals"]]
        self.assertGreaterEqual(len(ids),138)
        self.assertGreaterEqual(len(venues),19)
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(len(venues),len(set(venues)))
        for prior in ("go-c-20261216-rennes-hanry",
                      "go-c-20261202-saint-brieuc-magma",
                      "go-c-20270130-saint-brieuc-sbrbs"):
            self.assertIn(prior,ids)
        # Antipode was already in the public catalogue; it was not a new
        # signed venue in venueApprovals. Its concerts are preserved above.
        self.assertNotIn("antipode-rennes",venues)
        self.assertIn("bonjour-minuit-saint-brieuc",venues)

if __name__=="__main__":
    unittest.main()
