"""Cap Caval : publication exclusivement de la date signée par deux sources."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    CAP_CAVAL_SIGNED_20261105, PILOT_VENUES,
    validate_venue_approval, validate_approval,
)
FIXTURE=json.loads(r'''{"venueApproval":{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","venue":{"id":"salle-cap-caval-penmarch","name":"Salle Cap Caval","address":"Avenue de Skibbereen","postalCode":"29760","city":"Penmarc’h","department":"29","region":"Bretagne","latitude":47.81333,"longitude":-4.33766,"geoPrecision":"centre arrondi du bâtiment Salle Cap Caval désigné nominativement sur OpenStreetMap way 66608817 (amenity=music_venue, building=yes) via Mapcarta ; pas son entrée exacte ni un parking Cap Caval voisin","geoSource":"https://mapcarta.com/W66608817"},"officialEvidence":[{"url":"https://www.cap-caval.fr/infos-pratiques/","proofType":"official-venue-address","checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city"],"notes":"Le site officiel municipal confirme Salle Cap Caval, avenue de Skibbereen, 29760 Penmarc’h. Fiche du lieu distincte du stationnement."},{"url":"https://mapcarta.com/W66608817","proofType":"openstreetmap-venue-way","checkedAt":"2026-11-05","checkedFields":["venueName","coordinates"],"notes":"Mapcarta/OSM way 66608817 identifie le bâtiment Salle Cap Caval comme music venue et building=yes, 47.81333, -4.33766. À ne pas confondre avec les nœuds vélo Cap Caval 5752074999 ou 5752074945."}]},"approval":{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20270227-penmarch-howlin-jaws-komodor","title":"Howlin’ Jaws + Komodor","date":"2027-02-27","time":null,"artistIds":["howlin-jaws","komodor"],"venueId":"salle-cap-caval-penmarch","genres":["Psych Rock","Hard Rock"],"status":"confirmed","officialUrl":"https://www.cap-caval.fr/evenements/howlin-jaws-komodor/","sourceType":"salle","organizer":"Salle Cap Caval"},"newArtists":[],"officialEvidence":[{"url":"https://www.cap-caval.fr/evenements/howlin-jaws-komodor/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","eventStartTime"],"confirmedArtists":["Howlin’ Jaws","Komodor"],"notes":"Concert officiel de la salle municipale, samedi 27 février 2027 : Howlin’ Jaws & Komodor. Description explicite psych-rock et High-Energy Rock. Affichage 'Horaire début 20H30' sans précision garantie du début musical : event.time reste null."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["Howlin’ Jaws","Komodor"],"notes":"Agence officielle Howlin’ Jaws : 27 févr. 2027 PENMARC’H Cap Caval, « En première partie de Komodor ». La fiche salle affiche les deux groupes, sans préjuger de l'ordre musical."}]}}''')
CURRENT=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
TODAY=dt.date(2026,11,5)

class CapCavalTests(unittest.TestCase):
    def validated(self):
        venue=validate_venue_approval(FIXTURE["venueApproval"],TODAY)
        venues={x["id"]:x for x in CURRENT["venues"]}
        venues[venue["id"]]=venue
        artists={x["id"]:x for x in CURRENT["artists"]}
        return venue,venues,artists

    def test_original_building_is_not_a_car_park(self):
        venue,_,_=self.validated()
        self.assertEqual(venue,PILOT_VENUES["salle-cap-caval-penmarch"]["venue"])
        self.assertEqual(venue["geoSource"],"https://mapcarta.com/W66608817")
        self.assertEqual((venue["latitude"],venue["longitude"]),
                         (47.81333,-4.33766))
        self.assertIn("bâtiment",venue["geoPrecision"])
        self.assertNotIn("5752074999",venue["geoSource"])

    def test_only_signed_billed_event_without_musical_start(self):
        _,venues,artists=self.validated()
        event,new=validate_approval(FIXTURE["approval"],venues,artists,TODAY)
        self.assertEqual(event,CAP_CAVAL_SIGNED_20261105["event"])
        self.assertEqual(new,{})
        self.assertEqual(event["artistIds"],["howlin-jaws","komodor"])
        self.assertIsNone(event["time"])
        published = {x["id"]: x for x in CURRENT["events"]}
        if event["id"] in published:
            self.assertTrue(all(published[event["id"]].get(key) == event[key]
                                for key in ("id", "title", "date", "artistIds",
                                            "venueId", "genres", "status", "officialUrl", "sourceType")))
            self.assertIsNone(published[event["id"]].get("time"))

    def test_moved_event_false_artists_time_or_proof_cannot_pass(self):
        _,venues,artists=self.validated()
        variations=[
            ("wrong-venue",lambda row:row["event"].update(venueId="le-mem-rennes")),
            ("wrong-date",lambda row:row["event"].update(date="2027-03-27")),
            ("wrong-time",lambda row:row["event"].update(time="20:30")),
            ("wrong-artist",lambda row:row["event"].update(artistIds=["komodor"])),
            ("wrong-url",lambda row:row["event"].update(officialUrl="https://example.org/faux")),
            ("fake-proof",lambda row:row["officialEvidence"][1].update(url="https://example.org")),
            ("fake-genre",lambda row:row["event"].update(genres=["Techno"])),
            ("extra-new-artists",lambda row:row.update(newArtists=[{"id":"fake","name":"Fake"}])),
            ("auto-approved",lambda row:row.update(reviewedBy="automated-official-recheck")),
        ]
        for name,mutate in variations:
            row=copy.deepcopy(FIXTURE["approval"])
            mutate(row)
            with self.subTest(mutation=name):
                with self.assertRaises((ValueError,TypeError,KeyError)):
                    validate_approval(row,venues,artists,TODAY)

if __name__=="__main__":
    unittest.main()
