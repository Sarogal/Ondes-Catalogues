"""Revue indépendante : Cachemire + La Phaze + Bob's Not Dead, Grenoble."""
import copy
import json
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("approved.json")
ID = "go-c-20270227-grenoble-cachemire-la-phaze-bobs-not-dead"
URL = "https://www.la-belle-electrique.com/fr/agenda/tournee-du-coeur"
TOUR = "https://tourneeducoeur.ragetour.com/"
EXPECTED = {
    "id": ID, "title": "Cachemire + La Phaze + Bob's Not Dead",
    "date": "2027-02-27", "time": None,
    "artistIds": ["cachemire", "la-phaze", "bobs-not-dead"],
    "venueId": "la-belle-electrique-grenoble",
    "genres": ["Rock", "Punk"], "status": "confirmed",
    "officialUrl": URL, "sourceType": "salle", "organizer": "Rage Tour",
}

def check(row):
    if (row["reviewDecision"] != "approved"
            or row["reviewedBy"] != "independent-official-verifier"
            or row["reviewedAt"] != "2026-11-05"
            or row["event"] != EXPECTED
            or row["newArtists"] != []):
        raise ValueError("Identité nominative ou approbation altérée")
    proofs = row["officialEvidence"]
    if len(proofs) != 2:
        raise ValueError("Deux sources officielles requises")
    detail, tour = proofs
    if (detail.get("url") != URL
            or detail.get("proofType") != "official-organizer-or-venue"
            or detail.get("confirmedArtists") !=
                 ["Cachemire", "La Phaze", "Bob's Not Dead"]
            or not {"artists", "date", "venue", "genre"}.issubset(
                    set(detail.get("checkedFields") or []))
            or tour.get("url") != TOUR
            or tour.get("proofType") != "official-promoter-tour-calendar"
            or not {"date", "city", "venue"}.issubset(
                    set(tour.get("checkedFields") or []))
            or any(x.get("checkedAt") != "2026-11-05" for x in proofs)):
        raise ValueError("Preuve officielle ou artiste non confirmé")
    if any("concertStartTime" in x.get("checkedFields", [])
           or "startTime" in x.get("checkedFields", []) for x in proofs):
        raise ValueError("Début musical non attesté")
    return True

class TourneeDuCoeurGrenobleSignedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(PATH.read_text(encoding="utf-8"))
        cls.rows = data["approvals"]
        matching = [x for x in cls.rows if x["event"]["id"] == ID]
        assert len(matching) == 1
        cls.row = matching[0]

    def test_official_sources_and_strict_identity(self):
        self.assertTrue(check(self.row))
        self.assertEqual(len({x["event"]["id"] for x in self.rows}),
                         len(self.rows))
        self.assertIsNone(self.row["event"]["time"])
        self.assertEqual(len(self.row["event"]["artistIds"]), 3)

    def test_negative_attacks(self):
        for title, alter in [
            ("date", lambda x: x["event"].update(date="2027-02-28")),
            ("venue", lambda x: x["event"].update(venueId="la-laiterie-strasbourg")),
            ("hour", lambda x: x["event"].update(time="20:00")),
            ("lineup", lambda x: x["event"]["artistIds"].append("fictional-band")),
            ("source", lambda x: x["officialEvidence"][0].update(url="https://example.org")),
            ("reviewer", lambda x: x.update(reviewedBy="automated-official-recheck")),
            ("missing tour", lambda x: x["officialEvidence"].pop()),
        ]:
            row = copy.deepcopy(self.row)
            alter(row)
            with self.subTest(title=title), self.assertRaises(ValueError):
                check(row)

if __name__ == "__main__":
    unittest.main()
