"""Deux fiches Tournée du Cœur et une nouvelle salle signées individuellement."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
DB = json.loads((ROOT / "approved.json").read_text(encoding="utf-8"))
IDS = {
    "go-c-20270225-audincourt-cachemire-la-phaze-bobs-not-dead":
        ("2027-02-25", "le-moloco-audincourt", None,
         "https://www.lemoloco.com/agenda/cachemire-la-phaze-bobs-not-dead/"),
    "go-c-20270211-morlaix-cachemire-la-phaze-bobs-not-dead":
        ("2027-02-11", "le-sew-morlaix", "20:00",
         "https://sew-morlaix.com/evenements/la-tournee-du-coeur"),
}
BILL = ["cachemire", "la-phaze", "bobs-not-dead"]
TOUR = "https://tourneeducoeur.ragetour.com/"
GEO = (48.58309, -3.83484)
GEO_URL = "https://musitree.fr/concerts/salles/sew-la-manu-morlaix/"

def verify_event(row, key):
    date, venue, time, url = IDS[key]
    expected = {
        "id": key, "title": "Cachemire + La Phaze + Bob's Not Dead",
        "date": date, "time": time, "artistIds": BILL,
        "venueId": venue, "genres": ["Rock", "Punk"],
        "status": "confirmed", "officialUrl": url,
        "sourceType": "salle",
        "organizer": "Le Moloco" if time is None else "WART / Le SEW",
    }
    if (row.get("reviewDecision") != "approved" or
            row.get("reviewedBy") != "independent-official-verifier" or
            row.get("reviewedAt") != "2026-11-05" or
            row.get("event") != expected or row.get("newArtists") != []):
        raise ValueError("Affiche, date, horaire ou revue altérée")
    proofs = row.get("officialEvidence")
    if not isinstance(proofs, list) or len(proofs) != 2:
        raise ValueError("Fiche salle + tournée exigées")
    first, second = proofs
    if (first.get("url") != url or
            first.get("proofType") != "official-organizer-or-venue" or
            first.get("confirmedArtists") !=
                ["Cachemire", "La Phaze", "Bob's Not Dead"] or
            second.get("url") != TOUR or
            second.get("proofType") != "official-promoter-tour-calendar" or
            any(p.get("checkedAt") != "2026-11-05" for p in proofs) or
            not {"artists", "date", "venue", "genre"}.issubset(
                set(first.get("checkedFields") or [])) or
            not {"date", "city", "venue"}.issubset(
                set(second.get("checkedFields") or []))):
        raise ValueError("Preuve nominative incorrecte")
    has_start = "concertStartTime" in first["checkedFields"]
    if has_start != bool(time) or "startTime" in first["checkedFields"]:
        raise ValueError("Début musical inventé ou perdu")
    if time and first.get("concertStartTimeConfirmed") != time:
        raise ValueError("Heure musicale distincte non attestée")
    return True

def verify_venue(row):
    venue = row.get("venue") or {}
    if (row.get("reviewDecision") != "approved" or
            row.get("reviewedBy") != "independent-official-verifier" or
            row.get("reviewedAt") != "2026-11-05" or
            venue.get("id") != "le-sew-morlaix" or
            venue.get("name") != "Le SEW" or
            venue.get("address") != "39 quai du Léon" or
            venue.get("postalCode") != "29600" or
            venue.get("city") != "Morlaix" or
            (venue.get("latitude"), venue.get("longitude")) != GEO or
            venue.get("geoSource") != GEO_URL):
        raise ValueError("Nouvelle salle ou position non vérifiée")
    proofs = row.get("officialEvidence")
    if len(proofs) != 2 or [
        (p.get("url"), p.get("proofType"), p.get("checkedAt"))
        for p in proofs
    ] != [
        ("https://sew-morlaix.com/infos", "official-venue-address", "2026-11-05"),
        (GEO_URL, "independent-named-venue-geolocation", "2026-11-05"),
    ]:
        raise ValueError("Deux preuves indépendantes de localisation exigées")
    if not {"name", "address", "postalCode", "city"}.issubset(
            set(proofs[0].get("checkedFields") or [])) or not {
            "venueName", "coordinates"}.issubset(
            set(proofs[1].get("checkedFields") or [])):
        raise ValueError("Preuves de localisation insuffisantes")
    return True

class TourneeCoeurMolocoSewSignedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = {x["event"]["id"]: x for x in DB["approvals"]}
        cls.venues = {x["venue"]["id"]: x for x in DB["venueApprovals"]}

    def test_tournee_signatures_and_unique_ids(self):
        self.assertEqual(len(self.events), len(DB["approvals"]))
        self.assertEqual(len(self.venues), len(DB["venueApprovals"]))
        self.assertEqual(set(IDS) & set(self.events), set(IDS))
        for key in IDS:
            with self.subTest(key=key):
                self.assertTrue(verify_event(self.events[key], key))
        self.assertTrue(verify_venue(self.venues["le-sew-morlaix"]))

    def test_failed_mutations_of_event_and_start_times(self):
        for key in IDS:
            for name, mutate in (
                ("date", lambda x: x["event"].update(date="2027-05-28")),
                ("time", lambda x: x["event"].update(time="23:00")),
                ("newBand", lambda x: x["event"]["artistIds"].append("fake")),
                ("otherVenue", lambda x: x["event"].update(venueId="rockstore-montpellier")),
                ("fakeUrl", lambda x: x["officialEvidence"][0].update(url="https://fake.example/")),
                ("wrongBill", lambda x: x["officialEvidence"][0].update(confirmedArtists=["Fake"])),
                ("fakeStart", lambda x: x["officialEvidence"][0]["checkedFields"].append("concertStartTime")
                 if key.endswith("not-dead") and "audincourt" in key else
                 x["officialEvidence"][0]["checkedFields"].remove("concertStartTime")),
                ("reviewer", lambda x: x.update(reviewedBy="automated-official-recheck")),
            ):
                row=copy.deepcopy(self.events[key])
                mutate(row)
                with self.subTest(key=key,mutation=name), self.assertRaises(ValueError):
                    verify_event(row,key)

    def test_venue_mutation_rejected(self):
        for name, mutate in (
            ("lat", lambda x: x["venue"].update(latitude=48.65)),
            ("street", lambda x: x["venue"].update(address="Adresse inconnue")),
            ("source", lambda x: x["officialEvidence"][1].update(url="https://example.org/")),
            ("geo", lambda x: x["venue"].update(geoSource="inconnue")),
        ):
            row=copy.deepcopy(self.venues["le-sew-morlaix"])
            mutate(row)
            with self.subTest(mutation=name), self.assertRaises(ValueError):
                verify_venue(row)

if __name__ == "__main__":
    unittest.main()
