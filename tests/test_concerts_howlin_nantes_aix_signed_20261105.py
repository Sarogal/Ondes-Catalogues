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

    def historic_artists_before_gloria(self):
        # Rejouer le dossier signé à la date de sa première validation.
        # Gloria est désormais dans le catalogue publié et ne doit pas
        # faire rejeter a posteriori ce test d'approbation initial.
        return {x["id"]:x for x in PUBLIC["artists"] if x["id"]!="gloria"}

    def test_exact_venue_sources_and_independent_coordinates(self):
        for item in FIXTURE["venueApprovals"]:
            with self.subTest(id=item["venue"]["id"]):
                result=validate_venue_approval(item,TODAY)
                self.assertEqual(result,PILOT_VENUES[result["id"]]["venue"])
                self.assertEqual(result["geoSource"],item["officialEvidence"][1]["url"])

    def test_two_exact_events_pass_and_are_not_duplicates(self):
        venues=self.locations()
        artists=self.historic_artists_before_gloria()
        self.assertEqual(len(HOWLIN_TWO_SIGNED_20261105),2)
        published = {e["id"]:e for e in PUBLIC["events"]}
        for approval in FIXTURE["approvals"]:
            original = approval["event"]
            if original["id"] in published:
                self.assertTrue(all(
                    published[original["id"]].get(key)==original[key]
                    for key in ("id","title","date","artistIds","venueId",
                                "genres","status","officialUrl","sourceType")))
                self.assertEqual(published[original["id"]].get("time"),
                                 original["time"])
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
        artists=self.historic_artists_before_gloria()
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

    def test_reference_and_published_identities_are_preserved(self):
        # The cumulative 332-event cloud catalogue cannot be merged with
        # a two-event-only private fixture: the production guard requires
        # complete approvals for every previously published concert.
        # Check isolated approval validity, unique identities and retained
        # immutable baseline without forging earlier approval signatures.
        venues=self.locations()
        artists=self.historic_artists_before_gloria()
        old_venues={v["id"] for v in PUBLIC["venues"]}
        old_events={e["id"] for e in PUBLIC["events"]}
        old_artists={a["id"] for a in PUBLIC["artists"]}
        self.assertEqual(len(old_events),len(PUBLIC["events"]))
        self.assertEqual(len(old_venues),len(PUBLIC["venues"]))
        self.assertEqual(len(old_artists),len(PUBLIC["artists"]))
        self.assertTrue({e["id"] for e in REFERENCE["events"]}.issubset(old_events))
        self.assertTrue({v["id"] for v in REFERENCE["venues"]}.issubset(old_venues))
        self.assertTrue({a["id"] for a in REFERENCE["artists"]}.issubset(old_artists))
        published_venues={x["id"]:x for x in PUBLIC["venues"]}
        for ident in HOWLIN_TWO_VENUES & old_venues:
            self.assertEqual(published_venues[ident],PILOT_VENUES[ident]["venue"])
        published_events={x["id"]:x for x in PUBLIC["events"]}
        for ident in set(HOWLIN_TWO_SIGNED_20261105) & old_events:
            original=HOWLIN_TWO_SIGNED_20261105[ident]["event"]
            self.assertTrue(all(published_events[ident].get(k)==original[k]
                for k in ("id","title","date","artistIds","venueId","genres",
                          "status","officialUrl","sourceType")))
        if "gloria" in old_artists:
            self.assertEqual(next(x["name"] for x in PUBLIC["artists"] 
                                  if x["id"]=="gloria"),"Gloria")
        for x in FIXTURE["approvals"]:
            event,new=validate_approval(x,venues,artists,TODAY)
            self.assertEqual(event,x["event"])
            self.assertEqual(set(new),{"gloria"} if event["venueId"]=="6mic-aix-en-provence"
                             else set())
        self.assertEqual(len(FIXTURE["venueApprovals"]),2)
        self.assertEqual(len(FIXTURE["approvals"]),2)


if __name__=="__main__":
    unittest.main()
