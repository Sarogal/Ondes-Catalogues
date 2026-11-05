"""Dossiers officiels des quatre dernières dates Howlin' Jaws, revue manuelle obligatoire.

Les approbations cumulées publiées sont conservées par le synchroniseur réel.
Ce test hors réseau contrôle les quatre nouveaux dossiers exacts, sans trafiquer
la référence des 127 concerts ni remplacer le flux privé cumulatif.
"""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    HOWLIN_FINAL_FOUR_SIGNED_20261105, NEW_REFERENCE_GEO_SOURCES, PILOT_VENUES,
    validate_approval, validate_venue_approval, validate_new_reference_geo
)
TODAY=dt.date(2026,11,5)
PUBLIC=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
REFERENCE=json.loads((ROOT/"docs/grossesondes/concerts-reference.json").read_text(encoding="utf-8"))
FIXTURE=json.loads(r'''{"schema":"grossesondes.concert.approvals.v1","approvals":[{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20261110-roubaix-howlin-jaws-moundrag","title":"Howlin’ Jaws + Moundrag","date":"2026-11-10","time":"20:00","artistIds":["howlin-jaws","moundrag"],"venueId":"la-cave-aux-poetes-roubaix","genres":["Psych Rock"],"status":"confirmed","officialUrl":"https://caveauxpoetes.com/evenement/howlinjaws-moundrag/","sourceType":"salle","organizer":"La Cave aux Poètes"},"newArtists":[{"id":"moundrag","name":"Moundrag"}],"officialEvidence":[{"url":"https://caveauxpoetes.com/evenement/howlinjaws-moundrag/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","startTime"],"confirmedArtists":["Howlin' Jaws","Moundrag"],"concertStartTimeConfirmed":"20:00","notes":"Fiche officielle de La Cave aux Poètes: mar. 10 novembre 2026 Howlin' Jaws + Moundrag, portes 19h30, concerts 20h, rock indie psych."},{"url":"https://caveauxpoetes.com/agenda/","proofType":"first-party-venue-calendar","checkedAt":"2026-11-05","checkedFields":["artists","date","venue"],"notes":"Agenda officiel de La Cave aux Poètes : Howlin' Jaws / Moundrag, mar. 10 novembre 2026, salle la Cave aux Poètes ; la liste ne doit pas servir à inférer une heure."}]},{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20261118-paris-howlin-jaws-theo-charaf","title":"Howlin’ Jaws + Théo Charaf","date":"2026-11-18","time":null,"artistIds":["howlin-jaws","theo-charaf"],"venueId":"le-trabendo-paris","genres":["Rock"],"status":"confirmed","officialUrl":"https://www.letrabendo.net/programmation/howlin-jaws/","sourceType":"salle","organizer":"Radical Production"},"newArtists":[{"id":"theo-charaf","name":"Théo Charaf"}],"officialEvidence":[{"url":"https://www.letrabendo.net/programmation/howlin-jaws/","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","doorTime"],"confirmedArtists":["Howlin' Jaws","Théo Charaf"],"notes":"Fiche nominative officielle Trabendo : 18 novembre 2026, Howlin' Jaws + Théo Charaf ; ouverture des portes 19:00, pas de début musical confirmé. La tournée Radical nomme indépendamment Théo Charaf."}]},{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20261121-lyon-howlin-jaws-hayko","title":"Howlin’ Jaws + Hayko","date":"2026-11-21","time":"20:00","artistIds":["howlin-jaws","hayko"],"venueId":"marche-gare-lyon","genres":["Rock","Indie Rock"],"status":"confirmed","officialUrl":"https://marchegare.fr/agenda/howlin-jaws","sourceType":"salle","organizer":"Marché Gare"},"newArtists":[{"id":"hayko","name":"Hayko"}],"officialEvidence":[{"url":"https://marchegare.fr/agenda/howlin-jaws","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","concertStartTime"],"confirmedArtists":["Howlin' Jaws","Hayko"],"concertStartTimeConfirmed":"20:00","notes":"Fiche officielle du Marché Gare 21 novembre 2026, Howlin' Jaws + Hayko (release party), 20h début des concerts explicite, Grande Salle. Le lieu est au 4–6 place Hubert Mounier depuis sa rénovation, pas au parking voisin."},{"url":"https://www.fnacspectacles.com/event/howlin-jaws-le-marche-gare-lyon-02-21848689/","proofType":"authorized-ticket-distributor-full-date","checkedAt":"2026-11-05","checkedFields":["artists","date","venue"],"confirmedArtists":["Howlin' Jaws","Hayko"],"notes":"Fnac Spectacles : Howlin'Jaws + Hayko, samedi 21 novembre 2026 à 20h, Le Marché Gare Lyon 02. Le début musical provient exclusivement de la fiche organisateur."}]},{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","event":{"id":"go-c-20270429-nancy-howlin-jaws-komodor","title":"Howlin’ Jaws + Komodor","date":"2027-04-29","time":null,"artistIds":["howlin-jaws","komodor"],"venueId":"l-autre-canal-nancy","genres":["Psych Rock","Rock"],"status":"confirmed","officialUrl":"https://lautrecanalnancy.fr/agenda/howlin-jaws-komodor","sourceType":"salle","organizer":"L’Autre Canal"},"newArtists":[],"officialEvidence":[{"url":"https://lautrecanalnancy.fr/agenda/howlin-jaws-komodor","proofType":"official-organizer-or-venue","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","genre","eventTime"],"confirmedArtists":["Howlin' Jaws","Komodor"],"notes":"Fiche officielle L'Autre Canal : jeudi 29 avril 2027 20h30, Howlin' Jaws + Komodor, psyché rock, scène Club. 20h30 est l'horaire d'événement, pas nécessairement le début de la musique."},{"url":"https://radical-production.fr/artistes/howlin-jaws/","proofType":"independent-official-artist-agent","checkedAt":"2026-11-05","checkedFields":["artists","date","venue","coHeadline"],"confirmedArtists":["Howlin' Jaws","Komodor"],"notes":"Tournée officielle Radical : 29 avril 2027 Nancy Autre Canal, co-plateau avec Komodor. Aucune heure musicale inférée de cette source."}]}],"venueApprovals":[{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","venue":{"id":"marche-gare-lyon","name":"Marché Gare","address":"4–6 place Hubert Mounier","postalCode":"69002","city":"Lyon","department":"69","region":"Auvergne-Rhône-Alpes","latitude":45.74135,"longitude":4.82265,"geoPrecision":"centre indicatif du bâtiment Marché Gare (OpenStreetMap way 82189851 via Mapcarta), bâtiment arts_centre et building=yes avec site marchegare.fr ; la fiche OSM conserve l'ancienne adresse rue Casimir Périer, tandis que le site officiel 2026 indique l'accès actuel 4–6 place Hubert Mounier ; ni entrée précise ni parking LPA","geoSource":"https://mapcarta.com/W82189851"},"officialEvidence":[{"url":"https://marchegare.fr/infos-pratiques/acces-accessibilite","proofType":"official-venue-address","checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city"],"notes":"Page Accès & Accessibilité officielle : Marché Gare, 4-6 place Hubert Mounier, 69002 Lyon. Depuis rénovation 2022, ne pas retenir l'adresse rue Casimir Périer indiquée dans la fiche OSM ni le parking LPA voisin."},{"url":"https://mapcarta.com/W82189851","proofType":"openstreetmap-venue-way","checkedAt":"2026-11-05","checkedFields":["venueName","coordinates","officialWebsite"],"notes":"Mapcarta/OSM way 82189851 nomme Marché Gare, arts_centre, building=yes, et renvoie vers marchegare.fr ; centre du bâtiment 45.74135 / 4.82265, proche place Hubert Mounier. Fiche OSM contient encore 34 rue Casimir Périer : ne pas l'assimiler à l'accès actuel."}]}],"referenceVenueCorrections":[{"reviewDecision":"approved","reviewedBy":"independent-official-verifier","reviewedAt":"2026-11-05","venueId":"l-autre-canal-nancy","venuePatch":{"address":"45 boulevard d'Austrasie","postalCode":"54000","latitude":48.694175,"longitude":6.198269,"geoPrecision":"coordonnées GPS publiées par L'Autre Canal dans son dossier technique de 2023 (48.694175, 6.198269), concordant avec le bâtiment OSM way 115010861 à proximité; localisation indicative du site, pas une entrée garantie","geoSource":"https://lautrecanalnancy.fr/sites/default/files/lautrecanal/fichiers/dossier_technique_2023_fr.pdf"},"officialEvidence":[{"url":"https://lautrecanalnancy.fr/sites/default/files/lautrecanal/fichiers/dossier_technique_2023_fr.pdf","proofType":"official-venue-gps","checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city","latitude","longitude"],"notes":"Dossier technique officiel Grande Salle et Club mis à jour mai 2023, page de couverture: EPCC L'Autre Canal, 45 bd d'Austrasie 54000 Nancy; lat 48.694175 long 6.198269. La position ne prétend pas localiser la porte d'entrée."},{"url":"https://mapcarta.com/W115010861","proofType":"openstreetmap-venue-way","checkedAt":"2026-11-05","checkedFields":["venueName","coordinates"],"notes":"Mapcarta/OSM way 115010861 nomme le bâtiment L'Autre Canal (theater building, building=yes, lien officiel lautrecanalnancy.fr) à 48.6943,6.19858, proche des coordonnées publiées par la salle. À ne pas utiliser les coordonnées du P+R Deux Rives."}]}]}''')

class HowlinFourVerifiedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.approvals={x["event"]["id"]:x for x in FIXTURE["approvals"]}
        cls.venueApproval=FIXTURE["venueApprovals"][0]
        cls.geocorrection=FIXTURE["referenceVenueCorrections"][0]

    def known(self):
        venue=validate_venue_approval(self.venueApproval,TODAY)
        venues={x["id"]:x for x in PUBLIC["venues"]}
        venues[venue["id"]]=venue
        artists={x["id"]:x for x in PUBLIC["artists"]}
        # Ce test rejoue l'approbation de novembre sur l'état *avant*
        # publication. Les trois artistes sont désormais présents en public :
        # les conserver ferait échouer à tort la validation 'nouvel artiste'.
        for artist_id in ("moundrag", "theo-charaf", "hayko"):
            if artist_id not in artists:
                raise AssertionError("Artiste Howlin' Jaws publié manquant : " + artist_id)
            del artists[artist_id]
        return venues,artists

    def test_four_full_approvals_with_three_new_artists(self):
        venues,artists=self.known()
        self.assertEqual(len(HOWLIN_FINAL_FOUR_SIGNED_20261105),4)
        self.assertEqual(set(self.approvals),set(HOWLIN_FINAL_FOUR_SIGNED_20261105))
        published={x["id"]:x for x in PUBLIC["events"]}
        historic={x["id"] for x in REFERENCE["events"]}
        creations=set()
        for ident,entry in self.approvals.items():
            with self.subTest(id=ident):
                event,new=validate_approval(entry,venues,artists,TODAY)
                self.assertEqual(event,entry["event"])
                # Les quatre ajouts ont déjà été synchronisés : vérifier la
                # présence exacte en production, pas leur absence historique.
                self.assertIn(ident,published)
                self.assertNotIn(ident,historic)
                self.assertEqual(sum(x["id"]==ident for x in PUBLIC["events"]),1)
                for field in ("id","title","date","time","artistIds",
                              "venueId","genres","status","officialUrl","sourceType"):
                    self.assertEqual(published[ident].get(field),event.get(field))
                self.assertIsNone(event["time"] if ident.endswith("theo-charaf")
                                  or ident.endswith("nancy-howlin-jaws-komodor") else None)
                creations.update(new)
        self.assertEqual(creations,{"moundrag","theo-charaf","hayko"})

    def test_venue_osm_building_and_official_entry_not_parking(self):
        v=validate_venue_approval(self.venueApproval,TODAY)
        self.assertEqual(v,PILOT_VENUES["marche-gare-lyon"]["venue"])
        self.assertEqual(v["address"],"4–6 place Hubert Mounier")
        self.assertEqual((v["latitude"],v["longitude"]),(45.74135,4.82265))
        self.assertEqual(v["geoSource"],"https://mapcarta.com/W82189851")
        self.assertNotIn("W645595085",v["geoSource"])

    def test_nancy_geo_fix_exact_source_2026_without_baseline_edit(self):
        result=validate_new_reference_geo(FIXTURE,REFERENCE,TODAY)
        self.assertIn("l-autre-canal-nancy",result)
        self.assertEqual(result["l-autre-canal-nancy"],self.geocorrection)
        p=NEW_REFERENCE_GEO_SOURCES["l-autre-canal-nancy"]
        self.assertEqual(p["patch"],self.geocorrection["venuePatch"])
        self.assertEqual(p["checkedAt"],"2026-11-05")
        self.assertEqual(p["geoUrl"],"https://mapcarta.com/W115010861")
        self.assertEqual((p["patch"]["latitude"],p["patch"]["longitude"]),
                         (48.694175,6.198269))
        old=next(v for v in REFERENCE["venues"] if v["id"]=="l-autre-canal-nancy")
        self.assertEqual((old["latitude"],old["longitude"]),(48.692,6.185))
        self.assertEqual(len(NEW_REFERENCE_GEO_SOURCES),8)

    def test_no_artist_venue_time_or_evidence_forgery(self):
        venues,artists=self.known()
        attacks=[
            ("wrong-date",lambda a:a["event"].update(date="2027-12-31")),
            ("wrong-venue",lambda a:a["event"].update(venueId="le-mem-rennes")),
            ("wrong-artist",lambda a:a["event"].update(artistIds=["random"])),
            ("wrong-genre",lambda a:a["event"].update(genres=["Techno"])),
            ("wrong-url",lambda a:a["event"].update(officialUrl="https://example.org/false")),
            ("inferred-time",lambda a:a["event"].update(time="21:35")),
            ("unapproved",lambda a:a.update(reviewDecision="pending")),
            ("fake-proof",lambda a:a["officialEvidence"][0].update(url="https://example.org/false")),
            ("wrong-bill",lambda a:a["officialEvidence"][0].update(confirmedArtists=["Other"])),
            ("wrong-reviewer",lambda a:a.update(reviewedBy="automated-official-recheck")),
        ]
        for item in self.approvals.values():
            for title,modify in attacks:
                row=copy.deepcopy(item)
                modify(row)
                with self.subTest(id=item["event"]["id"],attack=title):
                    with self.assertRaises((ValueError,KeyError,TypeError)):
                        validate_approval(row,venues,artists,TODAY)

if __name__=="__main__":
    unittest.main()
