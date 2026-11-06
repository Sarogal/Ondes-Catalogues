"""Howlin' Jaws : 12 dates françaises (8 déjà publiques + 4 signées) et deux preuves géo."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).parent
APPROVED=json.loads((ROOT/"approved.json").read_text(encoding="utf-8"))
EVENTS={
    "go-c-20261110-roubaix-howlin-jaws-moundrag":
        ("2026-11-10","la-cave-aux-poetes-roubaix",["howlin-jaws","moundrag"],"20:00"),
    "go-c-20261118-paris-howlin-jaws-theo-charaf":
        ("2026-11-18","le-trabendo-paris",["howlin-jaws","theo-charaf"],None),
    "go-c-20261121-lyon-howlin-jaws-hayko":
        ("2026-11-21","marche-gare-lyon",["howlin-jaws","hayko"],"20:00"),
    "go-c-20270429-nancy-howlin-jaws-komodor":
        ("2027-04-29","l-autre-canal-nancy",["howlin-jaws","komodor"],None)
}
ROWS={row["event"]["id"]:row for row in APPROVED["approvals"]}
VENUES={row["venue"]["id"]:row for row in APPROVED["venueApprovals"]}

class HowlinFinalFourTests(unittest.TestCase):
    def test_four_verified_concerts_exactly_and_not_inferred(self):
        for ident,(date,venue,artists,time) in EVENTS.items():
            with self.subTest(ident=ident):
                approval=ROWS[ident]
                e=approval["event"]
                self.assertEqual((e["date"],e["venueId"],e["artistIds"],e["time"]),
                                 (date,venue,artists,time))
                self.assertEqual(approval["reviewedBy"],"independent-official-verifier")
                self.assertEqual(approval["reviewDecision"],"approved")
                self.assertEqual(approval["reviewedAt"],"2026-11-05")
                self.assertTrue(approval["officialEvidence"])
                self.assertTrue(all(p["checkedAt"]=="2026-11-05"
                                    for p in approval["officialEvidence"]))
                self.assertEqual(approval["officialEvidence"][0]["url"],e["officialUrl"])
                if time:
                    self.assertIn("startTime" if ident.startswith("go-c-20261110")
                                  else "concertStartTime",
                                  approval["officialEvidence"][0]["checkedFields"])
                else:
                    self.assertFalse(any("concertStartTime" in p["checkedFields"]
                                         or "startTime" in p["checkedFields"]
                                         for p in approval["officialEvidence"]))

    def test_new_artists_only_three_and_no_repeat_existing(self):
        expected={"moundrag","theo-charaf","hayko"}
        artists=[a for ident in EVENTS
                 for a in ROWS[ident]["newArtists"]]
        self.assertEqual({a["id"] for a in artists},expected)
        self.assertEqual(len(artists),3)
        self.assertEqual(ROWS["go-c-20270429-nancy-howlin-jaws-komodor"]["newArtists"],[])

    def test_lyon_actual_building_not_square_or_underground_parking(self):
        row=VENUES["marche-gare-lyon"]
        v=row["venue"]
        self.assertEqual((v["latitude"],v["longitude"]),(45.74135,4.82265))
        self.assertEqual(v["geoSource"],"https://mapcarta.com/W82189851")
        self.assertEqual(v["postalCode"],"69002")
        self.assertIn("Hubert Mounier",v["address"])
        self.assertEqual(row["officialEvidence"][0]["proofType"],"official-venue-address")
        self.assertEqual(row["officialEvidence"][1]["proofType"],"openstreetmap-venue-way")
        self.assertNotIn("W645595085",v["geoSource"])
        self.assertNotIn("N7544719211",v["geoSource"])

    def test_nancy_official_gps_correction_of_historic_city_centre(self):
        geo=next(x for x in APPROVED["referenceVenueCorrections"]
                 if x["venueId"]=="l-autre-canal-nancy")
        v=geo["venuePatch"]
        self.assertEqual((v["latitude"],v["longitude"]),(48.694175,6.198269))
        self.assertEqual(v["postalCode"],"54000")
        self.assertEqual(v["address"],"45 boulevard d'Austrasie")
        self.assertEqual(v["geoSource"],
          "https://lautrecanalnancy.fr/sites/default/files/lautrecanal/fichiers/dossier_technique_2023_fr.pdf")
        self.assertEqual([p["proofType"] for p in geo["officialEvidence"]],
                         ["official-venue-gps","openstreetmap-venue-way"])
        self.assertEqual(geo["officialEvidence"][1]["url"],
                         "https://mapcarta.com/W115010861")
        self.assertEqual(len(APPROVED["referenceVenueCorrections"]),10)

    def test_corroboration_is_not_misattributed(self):
        paris=ROWS["go-c-20261118-paris-howlin-jaws-theo-charaf"]
        self.assertEqual(paris["officialEvidence"][0]["confirmedArtists"],
                         ["Howlin' Jaws","Théo Charaf"])
        self.assertNotIn("startTime",paris["officialEvidence"][0]["checkedFields"])
        nancy=ROWS["go-c-20270429-nancy-howlin-jaws-komodor"]
        self.assertEqual(nancy["officialEvidence"][0]["proofType"],
                         "official-organizer-or-venue")
        self.assertEqual(nancy["officialEvidence"][1]["proofType"],
                         "independent-official-artist-agent")
        self.assertNotIn("startTime",nancy["officialEvidence"][0]["checkedFields"])

if __name__=="__main__":
    unittest.main()
