"""Contrôle conservateur du nouveau lieu Chato'do et de trois dates officielles."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENTS = {
    "go-c-20261105-blois-the-flying-bones": (
        "2026-11-05", "The Flying Bones", ["the-flying-bones"],
        ["the-flying-bones"],
        "https://chatodo.com/agenda/evenement/the-flying-bones/"),
    "go-c-20261112-blois-wicked-vessel": (
        "2026-11-12", "Wicked Vessel + Ultramoderne",
        ["wicked-vessel", "ultramoderne"],
        ["wicked-vessel", "ultramoderne"],
        "https://chatodo.com/agenda/evenement/wicked-vessel-ultramoderne/"),
    "go-c-20261203-blois-7weeks": (
        "2026-12-03", "7Weeks", ["7weeks"], [],
        "https://chatodo.com/agenda/evenement/7-weeks/"),
}


class SignedChatodoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
        cls.approved = {x["event"]["id"]: x for x in cls.document["approvals"]}

    def test_all_prior_approvals_remain_and_new_ids_are_unique(self):
        self.assertGreaterEqual(len(self.approved), 114)
        self.assertEqual(len(self.approved), len(self.document["approvals"]))
        self.assertLessEqual(len(self.approved), 400)

    def test_venue_blois_has_independently_verified_geo_not_entrance_guess(self):
        venue = next(x for x in self.document["venueApprovals"]
                     if x["venue"]["id"] == "le-chatodo-blois")
        self.assertEqual((venue["reviewDecision"], venue["reviewedBy"], venue["reviewedAt"]),
                         ("approved", "independent-official-verifier", "2026-11-03"))
        v = venue["venue"]
        self.assertEqual((v["name"], v["city"], v["department"]),
                         ("Le Chato'do", "Blois", "41"))
        self.assertEqual((v["address"], v["postalCode"]),
                         ("113 avenue de Vendôme", "41000"))
        self.assertEqual((v["latitude"], v["longitude"]), (47.60562, 1.31378))
        self.assertEqual(v["geoSource"], "https://mapcarta.com/fr/W118748447")
        self.assertEqual([(x["proofType"], x["url"]) for x in venue["officialEvidence"]], [
            ("official-venue-address", "https://chatodo.com/infos/venir/"),
            ("openstreetmap-venue-way", "https://mapcarta.com/fr/W118748447"),
        ])

    def test_three_exact_bills_genres_dates_proofs_and_no_door_time(self):
        new_artist_ids = []
        for event_id, (date, title, artist_ids, new_ids, url) in EVENTS.items():
            with self.subTest(event_id=event_id):
                entry = self.approved[event_id]
                e = entry["event"]
                self.assertEqual((e["date"], e["title"], e["artistIds"]),
                                 (date, title, artist_ids))
                self.assertEqual(e["venueId"], "le-chatodo-blois")
                self.assertEqual(e["officialUrl"], url)
                self.assertEqual(e["status"], "confirmed")
                self.assertEqual(e["sourceType"], "salle")
                self.assertIsNone(e["time"])
                self.assertEqual((entry["reviewDecision"], entry["reviewedBy"],
                                  entry["reviewedAt"]),
                                 ("approved", "independent-official-verifier", "2026-11-03"))
                proofs = entry["officialEvidence"]
                self.assertEqual(len(proofs), 2)
                self.assertEqual((proofs[0]["proofType"], proofs[0]["url"]),
                                 ("official-organizer-or-venue", url))
                self.assertTrue({"artists", "date", "venue", "genre"}.issubset(
                    set(proofs[0]["checkedFields"])))
                self.assertEqual((proofs[1]["proofType"], proofs[1]["url"]),
                                 ("first-party-venue-calendar", "https://chatodo.com/agenda/"))
                self.assertNotIn("date", proofs[1]["checkedFields"])
                self.assertEqual([x["id"] for x in entry["newArtists"]], new_ids)
                new_artist_ids.extend(new_ids)
        self.assertEqual(len(new_artist_ids), len(set(new_artist_ids)))
        self.assertNotIn("7weeks", new_artist_ids)


if __name__ == "__main__":
    unittest.main()
