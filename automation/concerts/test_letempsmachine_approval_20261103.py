"""Snapshot: venue Le Temps Machine et affiche Birdstone + Marave vérifiées."""
import json
from pathlib import Path
import unittest

DATA = json.loads((Path(__file__).resolve().parent / "approved.json").read_text(encoding="utf-8"))


class LeTempsMachineApprovalTests(unittest.TestCase):
    def test_independent_venue_address_and_geolocated_source(self):
        v = next(x for x in DATA["venueApprovals"]
                 if x["venue"]["id"] == "le-temps-machine-joue-les-tours")
        info = v["venue"]
        self.assertEqual((info["city"], info["department"], info["postalCode"]),
                         ("Joué-lès-Tours", "37", "37300"))
        self.assertIn("45-49 rue des Martyrs", info["address"])
        self.assertEqual((info["latitude"], info["longitude"]), (47.352189, 0.664716))
        self.assertIn("indicatives", info["geoPrecision"])
        self.assertEqual(v["reviewedBy"], "independent-official-verifier")
        self.assertEqual([p["proofType"] for p in v["officialEvidence"]],
                         ["official-venue-address", "independent-venue-gps"])
        self.assertEqual(v["officialEvidence"][0]["url"],
                         "https://letempsmachine.com/infos-pratiques/contacts")
        self.assertEqual(v["officialEvidence"][1]["url"],
                         "https://www.aleou.fr/salle-seminaire/26731-le-temps-machine")

    def test_event_exact_lineup_year_source_and_no_fabricated_start(self):
        a = next(x for x in DATA["approvals"] if x["event"]["id"] ==
                 "go-c-20261119-joue-les-tours-birdstone-marave")
        event = a["event"]
        self.assertEqual((event["date"], event["title"]),
                         ("2026-11-19", "Birdstone + Marave"))
        self.assertEqual(event["artistIds"], ["birdstone", "marave"])
        self.assertEqual(event["genres"], ["Progressive Rock", "Punk"])
        self.assertIsNone(event["time"])
        self.assertEqual(event["venueId"], "le-temps-machine-joue-les-tours")
        self.assertEqual(event["officialUrl"],
                         "https://letempsmachine.com/agenda/release-party-birdstone-marave")
        self.assertEqual([x["id"] for x in a["newArtists"]],
                         ["birdstone", "marave"])
        self.assertEqual(a["reviewedBy"], "independent-official-verifier")
        self.assertEqual(a["reviewedAt"], "2026-11-03")
        self.assertEqual({p["proofType"] for p in a["officialEvidence"]},
                         {"official-organizer-or-venue","first-party-venue-calendar"})
        self.assertTrue(all(p["checkedAt"]=="2026-11-03"
                            for p in a["officialEvidence"]))

    def test_preserve_all_other_approvals(self):
        self.assertGreaterEqual(len(DATA["venueApprovals"]), 16)
        self.assertIn("le-temps-machine-joue-les-tours",
                      {x["venue"]["id"] for x in DATA["venueApprovals"]})
        self.assertGreaterEqual(len(DATA["approvals"]), 115)
        self.assertEqual(len(DATA["approvals"]),
                         len({x["event"]["id"] for x in DATA["approvals"]}))


if __name__ == "__main__":
    unittest.main()
