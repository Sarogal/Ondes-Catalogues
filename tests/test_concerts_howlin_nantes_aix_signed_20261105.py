"""Nantes/Aix : approbations officielles exactes, aucune publication hors liste."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "scripts"))
from concerts_cloud_sync import (
    PILOT_VENUES, HOWLIN_TWO_SIGNED_20261105, HOWLIN_TWO_VENUES,
    validate_venue_approval, validate_approval, merge,
)

FIXTURE = json.loads(r'''{"schema":"grossesondes.concert.approvals.v1","venueApprovals":[{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","venue":{"id":"stereolux-nantes","name":"Stereolux","address":"4 boulevard Léon-Bureau","postalCode":"44200","city":"Nantes","department":"44","region":"Pays de la Loire","latitude":47.205119,"longitude":-1.563498,"geoPrecision":"point GPS nominatif Stereolux publié par Nantes Université (47.205119, -1.563498), cohérent avec le point OpenStreetMap node 2434544471 voisin ; repère indicatif de l'établissement, pas l'entrée exacte de la salle Maxi","geoSource":"https://www.univ-nantes.fr/plans-des-campus/stereolux"},"officialEvidence":[{"url":"https://stereolux.org/infos-pratiques/accessibilite","proofType":"official-venue-address","checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city"],"notes":"Site officiel : adresse au 4 boulevard Léon-Bureau, 44200 Nantes ; salle Maxi accessible par les Nefs. Le point GPS ne localise pas une entrée précise."},{"url":"https://www.univ-nantes.fr/plans-des-campus/stereolux","proofType":"independent-institutional-venue-gps","checkedAt":"2026-11-05","checkedFields":["venueName","coordinates"],"notes":"Nantes Université publie explicitement Stereolux à 47.205119, -1.563498, à l'adresse officielle ; concordance avec OpenStreetMap node 2434544471 (47.20509,-1.56354)."}]},{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","venue":{"id":"6mic-aix-en-provence","name":"6MIC","address":"160 rue Pascal Duverger","postalCode":"13090","city":"Aix-en-Provence","department":"13","region":"Provence-Alpes-Côte d’Azur","latitude":43.5193,"longitude":5.42182,"geoPrecision":"centre indicatif du bâtiment 6MIC identifié sur OpenStreetMap way 701032991 via Mapcarta (coordonnées arrondies à cinq décimales), pas son entrée exacte","geoSource":"https://mapcarta.com/fr/W701032991"},"officialEvidence":[{"url":"https://www.6mic-aix.fr/comment-venir-au-6mic/","proofType":"official-venue-address","checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city"],"notes":"6MIC confirme le 160 rue Pascal Duverger, 13090 Aix-en-Provence, quartier de la Constance."},{"url":"https://mapcarta.com/fr/W701032991","proofType":"openstreetmap-venue-way","checkedAt":"2026-11-05","checkedFields":["venueName","coordinates"],"notes":"Mapcarta d'après OpenStreetMap way 701032991 identifie nominativement le bâtiment 6mic au 160 rue Pascal Duverger ; centre de bâtiment arrondi 43.5193,5.42182, non l'accès spectateurs."}]}],"approvals":[{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20261208-nantes-fff-howlin-jaws","title":"FFF + Howlin’ Jaws","date":"2026-12-08","time":null,"artistIds":["fff","howlin-jaws"],"venueId":"stereolux-nantes","genres":["Funk Rock","Rock"],"status":"confirmed","officialUrl":"https://stereolux.org/agenda/fff","sourceType":"salle","organizer":"O Spectacles"},"newArtists":[],"officialEvidence":[{"url":"https://stereolux.org/agenda/fff","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["leadArtist","date","venue","supportUnspecified"],"confirmedArtists":["FFF"],"notes":"Fiche Stereolux du 8 décembre 2026 en salle Maxi, FFF avec '1ère partie' non nommée, 20 h affiché sans qualification explicite du début musical. Cette source NE prouve PAS le nom Howlin’ Jaws."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-support-agent","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","supportRole"],"confirmedArtists":["FFF","Howlin' Jaws"],"notes":"Agence officielle de Howlin’ Jaws : 08 déc. 2026 NANTES Stereolux en première partie de FFF ; identité de la première partie établie indépendamment de la fiche Stereolux."}]},{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20270402-aix-howlin-jaws-gloria","title":"Howlin’ Jaws + Gloria","date":"2027-04-02","time":null,"artistIds":["howlin-jaws","gloria"],"venueId":"6mic-aix-en-provence","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.6mic-aix.fr/evenements/club-indle-club-inde-w-howlin-jaws-gloria/","sourceType":"salle","organizer":"6MIC"},"newArtists":[{"id":"gloria","name":"Gloria"}],"officialEvidence":[{"url":"https://www.6mic-aix.fr/evenements/club-indle-club-inde-w-howlin-jaws-gloria/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre"],"confirmedArtists":["Howlin' Jaws","Gloria"],"notes":"Fiche 6MIC Club Indé vendredi 2 avril 2027 : Howlin' Jaws et Gloria, Rock. Séance annoncée 20 h 30 ; ne pas inférer l'heure du début musical de cette seule mention."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedAt":"2026-11-05","checkedFields":["leadArtist","date","venue","otherArtistNamed"],"confirmedArtists":["Howlin' Jaws","Gloria"],"notes":"Radical Production : 02 avr. 2027 Aix-en-Provence 6MIC, « Première partie : Gloria ». Le sens du plateau ne doit pas être inversé automatiquement."}]}]}''')
PUBLIC = json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
REFERENCE = json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
TODAY = dt.date(2026,11,5)

class HowlinJawsNantesAixSignedTests(unittest.TestCase):
    def locations(self):
        approved = [validate_venue_approval(x,TODAY) for x in FIXTURE["venueApprovals"]]
        self.assertEqual(len(approved),2)
        self.assertEqual({x["id"] for x in approved},HOWLIN_TWO_VENUES)
        return {**{v["id"]:v for v in PUBLIC["venues"]},
                **{v["id"]:v for v in approved}}

    def test_exact_venue_sources_and_independent_coordinates(self):
        for item in FIXTURE["venueApprovals"]:
            with self.subTest(id=item["venue"]["id"]):
                result=validate_venue_approval(item,TODAY)
                self.assertEqual(result,PILOT_VENUES[result["id"]]["venue"])
                self.assertEqual(result["geoSource"],item["officialEvidence"][1]["url"])

    def test_two_exact_events_pass_and_are_not_duplicates(self):
        venues=self.locations()
        artists={x["id"]:x for x in PUBLIC["artists"]}
        self.assertEqual(len(HOWLIN_TWO_SIGNED_20261105),2)
        self.assertFalse(any(x["event"]["id"] in {ev["id"] for ev in PUBLIC["events"]}
                             for x in FIXTURE["approvals"]))
        for item in FIXTURE["approvals"]:
            with self.subTest(id=item["event"]["id"]):
                ev,added=validate_approval(item,venues,artists,TODAY)
                self.assertEqual(ev,item["event"])
                self.assertEqual(set(added),
                                 {"gloria"} if item["event"]["venueId"]=="6mic-aix-en-provence"
                                 else set())
                self.assertIsNone(ev["time"])

    def test_mutations_forged_source_artist_time_venue_rejected(self):
        venues=self.locations()
        artists={x["id"]:x for x in PUBLIC["artists"]}
        mutations=[
            ("fake-date",lambda r:r["event"].update(date="2027-12-31")),
            ("fake-venue",lambda r:r["event"].update(venueId="le-mem-rennes")),
            ("fake-artist",lambda r:r["event"].update(artistIds=["unknown"])),
            ("fake-time",lambda r:r["event"].update(time="20:00")),
            ("fake-genre",lambda r:r["event"].update(genres=["Blues"])),
            ("fake-URL",lambda r:r["event"].update(officialUrl="https://example.com/fake")),
            ("fake-primary",lambda r:r["officialEvidence"][0].update(url="https://example.com")),
            ("fake-support",lambda r:r["officialEvidence"][1].update(confirmedArtists=["FFF"])),
            ("fake-extra-proof",lambda r:r["officialEvidence"].append(copy.deepcopy(r["officialEvidence"][0]))),
            ("fake-reviewedBy",lambda r:r.update(reviewedBy="automated-official-recheck")),
        ]
        for original in FIXTURE["approvals"]:
            for name,alter in mutations:
                row=copy.deepcopy(original)
                alter(row)
                with self.subTest(event=row["event"]["id"],mutation=name):
                    with self.assertRaises((KeyError,ValueError,TypeError)):
                        validate_approval(row,venues,artists,TODAY)

    def test_full_merge_adds_exactly_two_venues_two_events_one_artist(self):
        result,counts=merge(REFERENCE,PUBLIC,FIXTURE,TODAY)
        self.assertEqual(counts["newVenues"],2)
        self.assertEqual(counts["newEvents"],2)
        self.assertEqual(counts["newArtists"],1)
        self.assertEqual(counts["held"],[])
        self.assertEqual(len(result["venues"]),len(PUBLIC["venues"])+2)
        self.assertEqual(len(result["events"]),len(PUBLIC["events"])+2)
        self.assertEqual(len(result["artists"]),len(PUBLIC["artists"])+1)
        old_events={x["id"]:x for x in PUBLIC["events"]}
        self.assertTrue(all(x in {e["id"]:e for e in result["events"]}
                            and next(e for e in result["events"] if e["id"]==x)==v
                            for x,v in old_events.items()))

if __name__=="__main__":
    unittest.main()
