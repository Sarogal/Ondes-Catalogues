"""Deux concerts Howlin’ Jaws recoupés et deux salles précisément documentées.
Aucune écriture publique, réseau ou inférence de première partie.
"""
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("approved.json")
VENUES = {"stereolux-nantes": ("Nantes", 47.205119, -1.563498),
          "6mic-aix-en-provence": ("Aix-en-Provence", 43.5193, 5.42182)}
EVENTS = {
    "go-c-20261208-nantes-fff-howlin-jaws":
        ("2026-12-08", "stereolux-nantes", ["fff", "howlin-jaws"]),
    "go-c-20270402-aix-howlin-jaws-gloria":
        ("2027-04-02", "6mic-aix-en-provence", ["howlin-jaws", "gloria"]),
}

class HowlinJawsTwoDatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(SOURCE.read_text(encoding="utf-8"))
        cls.venues = {v["venue"]["id"]: v for v in cls.doc["venueApprovals"]}
        cls.events = {e["event"]["id"]: e for e in cls.doc["approvals"]}

    def test_venues_are_approved_with_independent_geo_and_address(self):
        for ident, (city, lat, lon) in VENUES.items():
            with self.subTest(ident=ident):
                approval = self.venues[ident]
                venue = approval["venue"]
                self.assertEqual(approval["reviewedBy"], "independent-official-verifier")
                self.assertEqual(approval["reviewDecision"], "approved")
                self.assertEqual(venue["city"], city)
                self.assertEqual((venue["latitude"], venue["longitude"]), (lat, lon))
                self.assertEqual(len(approval["officialEvidence"]), 2)
                self.assertEqual(
                    {x["proofType"] for x in approval["officialEvidence"]},
                    {"official-venue-address",
                     "independent-institutional-venue-gps" if ident=="stereolux-nantes"
                     else "openstreetmap-venue-way"})
                self.assertEqual(venue["geoSource"], approval["officialEvidence"][1]["url"])
                self.assertTrue(all(x["checkedAt"]=="2026-11-05"
                    for x in approval["officialEvidence"]))
                self.assertIn("pas", venue["geoPrecision"].lower())

    def test_event_dates_artists_and_no_inferred_times(self):
        for ident, (date, venue, artists) in EVENTS.items():
            with self.subTest(ident=ident):
                row=self.events[ident]
                ev=row["event"]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(ev["date"], date)
                self.assertEqual(ev["venueId"], venue)
                self.assertEqual(ev["artistIds"], artists)
                self.assertIsNone(ev["time"])
                self.assertEqual(ev["status"], "confirmed")
                self.assertEqual(len(row["officialEvidence"]), 2)
                self.assertNotEqual(row["officialEvidence"][0]["url"],
                                    row["officialEvidence"][1]["url"])
                self.assertEqual(row["officialEvidence"][0]["url"], ev["officialUrl"])

    def test_stereolux_first_party_does_not_falsely_claim_support(self):
        primary, promoter = self.events[
            "go-c-20261208-nantes-fff-howlin-jaws"]["officialEvidence"]
        self.assertEqual(primary["checkedFields"],
                         ["leadArtist","date","venue","supportUnspecified"])
        self.assertEqual(primary["confirmedArtists"], ["FFF"])
        self.assertEqual(promoter["confirmedArtists"], ["FFF", "Howlin' Jaws"])
        self.assertEqual(promoter["proofType"], "independent-official-support-agent")

    def test_aix_club_indie_adds_only_gloria(self):
        approval=self.events["go-c-20270402-aix-howlin-jaws-gloria"]
        self.assertEqual(approval["newArtists"], [{"id": "gloria", "name": "Gloria"}])
        self.assertIn("genre", approval["officialEvidence"][0]["checkedFields"])
        self.assertNotIn("concertStartTime",
                         approval["officialEvidence"][0]["checkedFields"])

if __name__=="__main__":
    unittest.main()
