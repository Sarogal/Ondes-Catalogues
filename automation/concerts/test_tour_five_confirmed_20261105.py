"""Non-régression du lot tournées du 05 novembre 2026, hors réseau.

La vérification porte sur les cinq concerts recoupés via les salles / producteurs
et les trois rectifications GPS documentées, sans écrire au catalogue public.
"""
import datetime as dt
import json
import unittest
from pathlib import Path

DOC = json.loads((Path(__file__).parent / "approved.json").read_text(encoding="utf-8"))
CASES = {
    "go-c-20261118-grenoble-inspector-cluzo": ("2026-11-18", "la-belle-electrique-grenoble", ["the-inspector-cluzo"], ["Rock"], None),
    "go-c-20261205-paris-skip-the-use": ("2026-12-05", "zenith-paris-la-villette-paris", ["skip-the-use"], ["Rock"], None),
    "go-c-20270122-paris-7weeks": ("2027-01-22", "la-maroquinerie-paris", ["7weeks"], ["Heavy Rock"], None),
    "go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes": ("2027-02-04", "le-transbordeur-villeurbanne", ["revnoir", "ice-sealed-eyes"], ["Metalcore"], "20:00"),
    "go-c-20270318-ramonville-skip-the-use": ("2027-03-18", "le-bikini-toulouse", ["skip-the-use"], ["Rock"], None),
}
GEO = {
    "zenith-paris-la-villette-paris": ("75019", 48.89418, 2.39317, "https://mapcarta.com/fr/W63971432"),
    "le-transbordeur-villeurbanne": ("69100", 45.78401, 4.86079, "https://mapcarta.com/fr/W85000536"),
    "la-belle-electrique-grenoble": ("38000", 45.18718, 5.70419, "https://mapcarta.com/fr/W299631312"),
}


class TourVerifiedBatchTests(unittest.TestCase):
    def test_identifiants_et_champs_non_inventes(self):
        grouped = {k: [row for row in DOC["approvals"] if row["event"]["id"] == k] for k in CASES}
        for eid, expected in CASES.items():
            with self.subTest(event=eid):
                self.assertEqual(len(grouped[eid]), 1)
                row = grouped[eid][0]
                event = row["event"]
                self.assertEqual((event["date"], event["venueId"], event["artistIds"], event["genres"], event["time"]), expected)
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedAt"], "2026-11-05")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["newArtists"], [])
                self.assertEqual(event["status"], "confirmed")
                self.assertEqual(event["sourceType"], "salle" if "7weeks" not in eid else "organisateur")
                self.assertEqual(len(row["officialEvidence"]), 2)
                self.assertEqual(event["officialUrl"], row["officialEvidence"][0]["url"])
                for evidence in row["officialEvidence"]:
                    self.assertTrue(evidence["url"].startswith("https://"))
                    self.assertEqual(evidence["checkedAt"], "2026-11-05")
                    self.assertTrue({"artists", "date", "venue"}.issubset(evidence["checkedFields"]))
                if event["time"] is None:
                    self.assertNotIn("timeMeaning", event)
                else:
                    self.assertEqual(event["timeMeaning"], "début du concert")

    def test_7weeks_guest_inconnu_ne_devient_pas_artiste(self):
        row = next(r for r in DOC["approvals"] if r["event"]["id"] == "go-c-20270122-paris-7weeks")
        self.assertEqual(row["event"]["title"], "7Weeks")
        self.assertEqual(row["event"]["artistIds"], ["7weeks"])
        self.assertIn("Guest", row["officialEvidence"][1]["notes"])
        self.assertNotIn("guest", str(row["newArtists"]).lower())

    def test_club_transbo_pas_une_nouvelle_salle_et_portes_distinctes(self):
        row = next(r for r in DOC["approvals"] if r["event"]["id"] == "go-c-20270204-villeurbanne-revnoir-ice-sealed-eyes")
        self.assertEqual(row["event"]["venueId"], "le-transbordeur-villeurbanne")
        self.assertEqual(row["event"]["time"], "20:00")
        self.assertIn("19h00", row["officialEvidence"][0]["notes"])
        self.assertIn("concertStartTime", row["officialEvidence"][0]["checkedFields"])
        self.assertNotIn("Club Transbo", [v["venue"]["id"] for v in DOC["venueApprovals"]])

    def test_concerts_deja_publies_ne_sont_pas_supprimes(self):
        old = {r["event"]["id"] for r in DOC["approvals"]}
        for item in (
            "go-c-20261106-limoges-7weeks",
            "go-c-20261120-saint-etienne-inspector-cluzo",
            "go-c-20270211-dijon-skip-the-use",
            "go-c-20270210-lorient-revnoir-ice-sealed-eyes",
        ):
            self.assertIn(item, old)

    def test_pas_de_collision_par_artiste_date_salle(self):
        rows = DOC["approvals"]
        for eid in CASES:
            event = next(r["event"] for r in rows if r["event"]["id"] == eid)
            matches = [r["event"]["id"] for r in rows
                       if r["event"]["date"] == event["date"]
                       and r["event"]["venueId"] == event["venueId"]
                       and set(r["event"]["artistIds"]) & set(event["artistIds"])]
            self.assertEqual(matches, [eid])

    def test_trois_salles_geocodees_avec_sources_openstreetmap(self):
        for venue_id, (postal, lat, lon, url) in GEO.items():
            with self.subTest(venue_id=venue_id):
                records = [r for r in DOC["referenceVenueCorrections"] if r["venueId"] == venue_id]
                self.assertEqual(len(records), 1)
                row = records[0]
                patch = row["venuePatch"]
                self.assertEqual(patch["postalCode"], postal)
                self.assertEqual(patch["latitude"], lat)
                self.assertEqual(patch["longitude"], lon)
                self.assertEqual(patch["geoSource"], url)
                self.assertIn("bâtiment", patch["geoPrecision"])
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedAt"], "2026-11-05")
                self.assertEqual([p["checkedAt"] for p in row["officialEvidence"]],
                                 ["2026-11-05", "2026-11-05"])
                self.assertEqual(row["officialEvidence"][1]["url"], url)
                self.assertEqual(row["officialEvidence"][0]["proofType"], "official-venue-address")
                self.assertEqual(row["officialEvidence"][1]["proofType"], "openstreetmap-venue-way")

    def test_pas_de_gps_de_entree_supposee(self):
        for venue_id in GEO:
            row = next(r for r in DOC["referenceVenueCorrections"] if r["venueId"] == venue_id)
            self.assertTrue(row["venuePatch"]["geoPrecision"].lower().startswith("position indicative du bâtiment"))
            self.assertTrue(all("coordinates" not in p["checkedFields"] or p["url"].startswith("https://mapcarta.com")
                                for p in row["officialEvidence"]))


if __name__ == "__main__":
    unittest.main()
