"""Four independently checked Tetris concerts: exact bills and year provenance."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
ROWS = {x["event"]["id"]: x for x in DOC["approvals"]}
EXPECTED = {
    "go-c-20261113-lehavre-edging-zonbi":
        ("2026-11-13", ["edging","zonbi"], "event-partner-full-date"),
    "go-c-20261127-lehavre-fff-metro-verlaine":
        ("2026-11-27", ["fff","metro-verlaine"], "official-tourism-full-date"),
    "go-c-20261205-lehavre-coffin-belek":
        ("2026-12-05", ["coffin","belek"], "independent-concert-calendar-full-date"),
    "go-c-20261212-lehavre-the-inspector-cluzo-grimskunk":
        ("2026-12-12", ["the-inspector-cluzo","grimskunk"],
         "official-artist-tour-full-date"),
}


class TetrisSignedApprovals(unittest.TestCase):
    def test_venue_independent_official_address_and_tourism_geopoint(self):
        x = next(x for x in DOC["venueApprovals"]
                 if x["venue"]["id"]=="le-tetris-le-havre")
        v=x["venue"]
        self.assertEqual((v["name"],v["city"],v["postalCode"]),
                         ("Le Tetris","Le Havre","76620"))
        self.assertEqual((v["latitude"],v["longitude"]),
                         (49.5043853,0.1206928))
        self.assertIn("indicative",v["geoPrecision"])
        self.assertEqual(x["reviewedBy"], "independent-official-verifier")
        self.assertEqual([e["proofType"] for e in x["officialEvidence"]],
                         ["official-venue-address","independent-tourism-gps"])
        self.assertEqual(x["officialEvidence"][0]["url"],
                         "https://letetris.fr/infos-pratiques/venir")
        self.assertEqual(x["officialEvidence"][1]["url"],
                         "https://www.cirkwi.com/fr/point-interet/2508080-le-tetris")

    def test_four_full_year_proofs_lineups_and_no_invented_times(self):
        for key,(date,artists,year_proof) in EXPECTED.items():
            with self.subTest(key=key):
                row = ROWS[key]
                ev = row["event"]
                self.assertEqual(ev["date"],date)
                self.assertEqual(ev["artistIds"],artists)
                self.assertEqual(ev["venueId"],"le-tetris-le-havre")
                self.assertEqual(ev["status"],"confirmed")
                self.assertEqual(ev["sourceType"],"salle")
                self.assertIsNone(ev["time"])
                self.assertEqual(row["reviewedBy"],"independent-official-verifier")
                self.assertEqual(row["reviewedAt"],"2026-11-03")
                self.assertEqual([p["proofType"] for p in row["officialEvidence"]],
                                 ["official-organizer-or-venue",year_proof])
                self.assertIn("dayMonth",
                              row["officialEvidence"][0]["checkedFields"])
                self.assertIn("fullDate",
                              row["officialEvidence"][1]["checkedFields"])
                self.assertTrue(all(p["checkedAt"]=="2026-11-03"
                                    for p in row["officialEvidence"]))

    def test_no_artist_duplication_with_existing_fff_or_inspector(self):
        new_ids=[a["id"] for key in EXPECTED
                 for a in ROWS[key]["newArtists"]]
        self.assertEqual(len(new_ids),6)
        self.assertEqual(len(new_ids),len(set(new_ids)))
        self.assertNotIn("fff",new_ids)
        self.assertNotIn("the-inspector-cluzo",new_ids)
        self.assertGreaterEqual(len(DOC["venueApprovals"]), 19)
        self.assertGreaterEqual(len(DOC["approvals"]),119)


if __name__=="__main__":
    unittest.main()
