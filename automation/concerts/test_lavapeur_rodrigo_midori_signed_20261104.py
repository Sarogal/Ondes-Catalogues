"""Non-régression de l'approbation Rodrigo y Gabriela / midori jaeger à La Vapeur.

Aucun accès réseau. Contrôles de provenance, de géographie, de dates et de doublons.
Le concert ne sera publiable qu'après fusion de la signature côté catalogue public.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOC = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
ID = "go-c-20270407-dijon-rodrigo-y-gabriela-midori-jaeger"
OFFICIAL = "https://www.lavapeur.com/programme/rodrigo-y-gabriela"
BOOKING = "https://billetterie.lavapeur.com/agenda/840-Rodrigo-y-Gabriela?session=840"


class RodrigoMidoriPrivateApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = [row for row in DOC["approvals"] if row["event"]["id"] == ID]
        cls.record = cls.records[0] if cls.records else None

    def test_exact_signed_lineup_and_no_unproven_music_start(self):
        self.assertEqual(len(self.records), 1)
        row = self.record
        e = row["event"]
        self.assertEqual((row["reviewDecision"], row["reviewedBy"], row["reviewedAt"]),
                         ("approved", "independent-official-verifier", "2026-11-04"))
        self.assertEqual((e["title"], e["date"], e["venueId"]),
                         ("Rodrigo y Gabriela + midori jaeger", "2027-04-07",
                          "la-vapeur-dijon"))
        self.assertEqual(e["artistIds"], ["rodrigo-y-gabriela", "midori-jaeger"])
        self.assertEqual(e["genres"], ["Rock instrumental"])
        self.assertEqual((e["sourceType"], e["status"], e["officialUrl"]),
                         ("salle", "confirmed", OFFICIAL))
        self.assertIsNone(e["time"])
        self.assertEqual(row["newArtists"], [])

    def test_two_first_party_nominative_proofs_only(self):
        self.assertEqual(len(self.records), 1)
        proofs = self.record["officialEvidence"]
        self.assertEqual(len(proofs), 2)
        self.assertEqual([(p["url"], p["proofType"], p["checkedFields"])
                          for p in proofs], [
            (OFFICIAL, "official-organizer-or-venue",
             ["artists", "date", "venue", "genre"]),
            (BOOKING, "official-venue-ticketing-detail",
             ["artists", "date", "venue"]),
        ])
        for p in proofs:
            self.assertEqual(p["checkedAt"], "2026-11-04")
            self.assertTrue(p["url"].startswith("https://"))
            self.assertFalse({"doorTime", "startTime", "concertStartTime"}
                             & set(p["checkedFields"]))

    def test_no_duplicate_artist_on_same_day_at_same_venue(self):
        self.assertEqual(len(self.records), 1)
        e = self.record["event"]
        for other in DOC["approvals"]:
            if other is self.record:
                continue
            o = other["event"]
            if o["date"] == e["date"] and o["venueId"] == e["venueId"]:
                self.assertFalse(set(o["artistIds"]) & set(e["artistIds"]))

    def test_previous_dijon_events_and_venue_remain_approved(self):
        by_id = {r["event"]["id"]: r for r in DOC["approvals"]}
        for historic_id in (
            "go-c-20270123-dijon-misanthrope-obsession-slapdown",
            "go-c-20270211-dijon-skip-the-use",
            "go-c-20270409-reims-rodrigo-y-gabriela",
        ):
            self.assertEqual(by_id[historic_id]["reviewDecision"], "approved")
        venues = {r["venue"]["id"]: r["venue"] for r in DOC["venueApprovals"]}
        self.assertIn("la-vapeur-dijon", venues)
        self.assertEqual(venues["la-vapeur-dijon"]["city"], "Dijon")


if __name__ == "__main__":
    unittest.main()
