"""Réconciliation documentaire des salles de tournées, hors réseau."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artist_tour_venue_hints as hints
import artist_tour_discovery as discovery
import intake_archive

CATALOG = {
    "schemaVersion": 1,
    "artists": [
        {"id": "7weeks", "name": "7Weeks"},
        {"id": "revnoir", "name": "Revnoir"},
        {"id": "skip-the-use", "name": "Skip The Use"},
        {"id": "the-inspector-cluzo", "name": "The Inspector Cluzo"},
        {"id": "marillion", "name": "Marillion"},
        {"id": "howlin-jaws", "name": "Howlin\u0027 Jaws"}],
    "venues": [
        {"id": "espace-john-lennon-limoges", "name": "Espace John Lennon",
         "city": "Limoges"},
        {"id": "le-transbordeur-villeurbanne", "name": "Le Transbordeur",
         "city": "Villeurbanne"},
        {"id": "le-bikini-toulouse", "name": "Le Bikini",
         "city": "Ramonville-Saint-Agne"},
        {"id": "casino-de-paris", "name": "Casino de Paris",
         "city": "Paris"},
        {"id": "radiant-bellevue-caluire", "name": "Radiant-Bellevue",
         "city": "Caluire-et-Cuire"},
        {"id": "cepac-silo-marseille", "name": "CEPAC Silo",
         "city": "Marseille"},
        {"id": "le-mem-rennes", "name": "Le MeM",
         "city": "Rennes"},
        {"id": "la-cave-aux-poetes-roubaix", "name": "La Cave aux Poètes",
         "city": "Roubaix"},
        {"id": "le-trabendo-paris", "name": "Le Trabendo",
         "city": "Paris"},
        {"id": "la-carene-brest", "name": "La Carène",
         "city": "Brest"},
        {"id": "le-chabada-angers", "name": "Le Chabada",
         "city": "Angers"},
        {"id": "le-fil-saint-etienne", "name": "Le Fil",
         "city": "Saint-Étienne"},
        {"id": "la-laiterie-strasbourg", "name": "La Laiterie",
         "city": "Strasbourg"},
        {"id": "l-autre-canal-nancy", "name": "L’Autre Canal",
         "city": "Nancy"},
        {"id": "salle-cap-caval-penmarch", "name": "Salle Cap Caval",
         "city": "Penmarc’h"},
        {"id": "stereolux-nantes", "name": "Stereolux",
         "city": "Nantes"},
        {"id": "6mic-aix-en-provence", "name": "6MIC",
         "city": "Aix-en-Provence"}],
    "events": [],
}
HINTS = {
    "schema": hints.SCHEMA,
    "hints": [
        {"artistId": "7weeks", "reportedCity": "LIMOGES",
         "reportedVenue": "CCM JOHN LENNON", "canonicalCity": "Limoges",
         "canonicalVenueId": "espace-john-lennon-limoges",
         "officialEvidenceUrl": "https://centresculturels.limoges.fr/se-rendre-dans-les-centres-culturels"},
        {"artistId": "revnoir", "reportedCity": "Villeurbanne",
         "reportedVenue": "Club Transbo", "canonicalCity": "Villeurbanne",
         "roomWithinVenue": True,
         "canonicalVenueId": "le-transbordeur-villeurbanne",
         "officialEvidenceUrl": "https://www.transbordeur.fr/evenement/revnoir-ice-sealed-eyes-04022027/"},
        {"artistId": "skip-the-use", "reportedCity": "Lyon",
         "reportedVenue": "Le Radiant Bellevue", "canonicalCity": "Caluire-et-Cuire",
         "canonicalVenueId": None,
         "officialEvidenceUrl": "https://www.archive.radiant-bellevue.fr/le-radiant/"},
    ],
}
CANDIDATES = [
    {"candidateId": "artist-tour:limoges", "artistId": "7weeks",
     "city": "LIMOGES", "venue": "CCM JOHN LENNON",
     "date": "2026-11-06", "name": "7Weeks", "leadArtist": "7Weeks",
     "sourceUrl": "https://7weeks.fr/concerts/", "publicationAllowed": False,
     "reviewRequired": True, "newVenueToReview": True},
    {"candidateId": "artist-tour:villeurbanne", "artistId": "revnoir",
     "city": "Villeurbanne", "venue": "Club Transbo",
     "date": "2027-02-04", "name": "REVNOIR + ICE SEALED EYES", "leadArtist": "Revnoir",
     "sourceUrl": "https://slhproductions.fr/agenda/revnoir2027/", "publicationAllowed": False,
     "reviewRequired": True, "newVenueToReview": True},
    {"candidateId": "artist-tour:caluire", "artistId": "skip-the-use",
     "city": "Lyon", "venue": "Le Radiant Bellevue",
     "date": "2027-01-30", "name": "Skip The Use", "leadArtist": "Skip The Use",
     "sourceUrl": "https://www.livenation.fr/event/skip-the-use-love-and-anxiety-lyon-tickets-edp1665823",
     "publicationAllowed": False, "reviewRequired": True, "newVenueToReview": True},
]


class VerifiedVenueHintsTests(unittest.TestCase):
    def test_identification_deux_salles_connues(self):
        output, hits = hints.annotate(CANDIDATES, CATALOG, HINTS)
        self.assertEqual(len(hits), 3)
        self.assertEqual(output[0]["venueIdIfKnown"], "espace-john-lennon-limoges")
        self.assertFalse(output[0]["newVenueToReview"])
        self.assertEqual(output[1]["venueIdIfKnown"], "le-transbordeur-villeurbanne")
        self.assertFalse(output[1]["newVenueToReview"])
        self.assertTrue(output[1]["venueReconciliation"]["roomWithinVenue"])

    def test_radiant_reste_a_reviser_commune_correcte(self):
        output, _ = hints.annotate(CANDIDATES, CATALOG, HINTS)
        row = output[2]
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual(row["venueReconciliation"]["canonicalCity"], "Caluire-et-Cuire")
        self.assertTrue(row["venueReconciliation"]["cityCorrectionRequired"])
        self.assertIsNone(row.get("venueIdIfKnown"))
        self.assertTrue(row["newVenueToReview"])
        self.assertFalse(row["publicationAllowed"])

    def test_les_ids_originales_et_la_source_restent_inchanges(self):
        before = copy.deepcopy(CANDIDATES)
        output, _ = hints.annotate(CANDIDATES, CATALOG, HINTS)
        self.assertEqual([x["candidateId"] for x in output],
                         [x["candidateId"] for x in before])
        self.assertEqual([x["sourceUrl"] for x in output],
                         [x["sourceUrl"] for x in before])
        self.assertEqual(CANDIDATES, before)
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"]
                            for x in output))

    def test_pas_de_rapprochement_fuzzy(self):
        different = [dict(CANDIDATES[0], venue="Salle John Lennon inconnue")]
        output, hits = hints.annotate(different, CATALOG, HINTS)
        self.assertEqual(hits, [])
        self.assertNotIn("venueReconciliation", output[0])

    def test_refus_contradiction_ou_source_non_justifiee(self):
        invalids = [
            dict(HINTS["hints"][0], canonicalVenueId="id-inconnu"),
            dict(HINTS["hints"][0], canonicalCity="Lyon"),
            dict(HINTS["hints"][0], officialEvidenceUrl="http://insecure.fr"),
        ]
        for invalid in invalids:
            with self.assertRaises(ValueError):
                hints.validate_hints({"schema": hints.SCHEMA, "hints": [invalid]}, CATALOG)
        bad = {"schema": hints.SCHEMA, "hints": [
            HINTS["hints"][0], HINTS["hints"][0]]}
        with self.assertRaises(ValueError):
            hints.validate_hints(bad, CATALOG)

    def test_compatibilite_archivage_audit_prive(self):
        annotated, _ = hints.annotate(CANDIDATES, CATALOG, HINTS)
        report = discovery.build_report(CATALOG, {"sources": []}, __import__("datetime").date(2026,11,5), annotated, [])
        archived, diff = intake_archive.merge(None, report, "2026-11-05T05:00:00Z")
        self.assertEqual(diff["added"], 3)
        self.assertEqual(archived["total"], 3)

    def test_parthenay_orthographe_officielle(self):
        rows = [dict(CANDIDATES[0], candidateId="artist-tour:parthenay",
                     artistId="the-inspector-cluzo", city="PARTENAY", venue="Diff’Art")]
        out, checked = hints.annotate(rows, CATALOG, hints.load())
        self.assertEqual(len(checked), 1)
        self.assertEqual(out[0]["venueReconciliation"]["canonicalCity"], "Parthenay")
        self.assertTrue(out[0]["venueReconciliation"]["cityCorrectionRequired"])
        self.assertEqual(out[0]["city"], "PARTENAY")
        self.assertFalse(out[0]["publicationAllowed"])


    def test_marillion_toulouse_ramonville_alias_sans_deplacer_la_salle(self):
        source_row = {
            "candidateId": "artist-tour:marillion-20261125",
            "artistId": "marillion", "date": "2026-11-25",
            "city": "Toulouse", "venue": "Le Bikini",
            "name": "Marillion", "leadArtist": "Marillion",
            "sourceUrl": "https://www.marillion.com/tour/",
            "newVenueToReview": True,
            "publicationAllowed": False, "reviewRequired": True,
        }
        out, hits = hints.annotate([source_row], CATALOG, hints.load())
        self.assertEqual(hits, [source_row["candidateId"]])
        self.assertEqual(out[0]["city"], "Toulouse")
        self.assertEqual(out[0]["venue"], "Le Bikini")
        self.assertEqual(out[0]["venueIdIfKnown"], "le-bikini-toulouse")
        self.assertFalse(out[0]["newVenueToReview"])
        self.assertEqual(out[0]["venueReconciliation"]["canonicalCity"],
                         "Ramonville-Saint-Agne")
        self.assertTrue(out[0]["venueReconciliation"]["cityCorrectionRequired"])
        self.assertFalse(out[0]["publicationAllowed"])
        self.assertTrue(out[0]["reviewRequired"])
        self.assertNotIn("latitude", out[0])
        self.assertNotIn("longitude", out[0])
        self.assertNotIn("venueIdIfKnown", source_row)

    def test_marillion_three_new_venues_exactly_recognized(self):
        observed = [
            ("2026-11-21", "Paris", "Casino De Paris", "casino-de-paris", False),
            ("2026-11-29", "Lyon", "Radiant-Bellevue", "radiant-bellevue-caluire", True),
            ("2027-05-15", "Marseille", "Le Silo", "cepac-silo-marseille", False),
            ("2027-05-16", "Marseille", "Le Silo", "cepac-silo-marseille", False),
        ]
        original = [
            {"candidateId": "artist-tour:marillion-" + day,
             "artistId": "marillion", "date": day, "name": "Marillion",
             "leadArtist": "Marillion", "city": city, "venue": venue,
             "sourceUrl": "https://www.marillion.com/tour/",
             "newVenueToReview": True, "reviewRequired": True,
             "publicationAllowed": False}
            for day,city,venue,ident,corrected in observed
        ]
        updated, hits = hints.annotate(original, CATALOG, hints.load())
        self.assertEqual(len(hits), 4)
        for row, baseline, (day,city,venue,ident,corrected) in zip(updated, original, observed):
            with self.subTest(day=day):
                self.assertEqual(row["candidateId"], baseline["candidateId"])
                self.assertEqual(row["city"], city)
                self.assertEqual(row["venue"], venue)
                self.assertEqual(row["venueIdIfKnown"], ident)
                self.assertFalse(row["newVenueToReview"])
                self.assertEqual(row["venueReconciliation"]["cityCorrectionRequired"], corrected)
                self.assertEqual(row["venueReconciliation"]["status"], "review_only")
                self.assertTrue(row["reviewRequired"])
                self.assertFalse(row["publicationAllowed"])
                self.assertNotIn("latitude", row)
                self.assertNotIn("longitude", row)

    def test_existing_skip_the_use_lyon_hint_now_has_exact_caluire_venue(self):
        candidate = dict(CANDIDATES[2])
        observed, hits = hints.annotate([candidate], CATALOG, hints.load())
        self.assertEqual(len(hits), 1)
        row = observed[0]
        self.assertEqual(row["venueIdIfKnown"], "radiant-bellevue-caluire")
        self.assertFalse(row["newVenueToReview"])
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual(row["venueReconciliation"]["canonicalCity"], "Caluire-et-Cuire")
        self.assertTrue(row["venueReconciliation"]["cityCorrectionRequired"])
        self.assertFalse(row["publicationAllowed"])

    def test_reject_wrong_alias_city_and_unregistered_venue(self):
        known = hints.load()
        triplet = next(x for x in known["hints"] if x["artistId"] == "marillion"
                       and x["reportedVenue"] == "Radiant-Bellevue")
        for changed in (dict(triplet, canonicalCity="Lyon"),
                        dict(triplet, canonicalVenueId="unknown"),
                        dict(triplet, officialEvidenceUrl="http://example.org")):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    hints.validate_hints({"schema": hints.SCHEMA, "hints": [changed]}, CATALOG)
        # Les genres, dates et noms d'artiste ne sont jamais corrigés par une
        # correspondance de lieu, même documentée.
        bogus = {"candidateId":"bogus","artistId":"marillion","date":"2028-03-03",
                 "city":"Lyon","venue":"Radiant-Bellevue",
                 "name":"Marillion","publicationAllowed":False,
                 "reviewRequired":True}
        out, _ = hints.annotate([bogus], CATALOG, known)
        self.assertEqual(out[0]["date"], "2028-03-03")
        self.assertFalse(out[0]["publicationAllowed"])


    def test_marillion_rennes_ancien_nom_vers_nouveau_mem_geolocalise(self):
        import triage
        published = {
            "artists": CATALOG["artists"] + [{"id":"lazuli","name":"Lazuli"}],
            "venues": CATALOG["venues"],
            "events": [{
                "id":"go-c-20261118-rennes-marillion-lazuli",
                "title":"Marillion + Lazuli","date":"2026-11-18",
                "venueId":"le-mem-rennes","artistIds":["marillion","lazuli"]}],
        }
        row = {
            "candidateId":"artist-tour:marillion-20261118",
            "artistId":"marillion","date":"2026-11-18",
            "city":"Rennes","venue":"Le Mem",
            "name":"Marillion","leadArtist":"Marillion",
            "sourceUrl":"https://www.marillion.com/tour/",
            "newVenueToReview":True,
            "reviewRequired":True,"publicationAllowed":False,
        }
        updated, matched = hints.annotate([row], published, hints.load())
        self.assertEqual(matched,[row["candidateId"]])
        out=updated[0]
        self.assertEqual(out["venueIdIfKnown"],"le-mem-rennes")
        self.assertFalse(out["newVenueToReview"])
        self.assertEqual(out["city"],"Rennes")
        self.assertEqual(out["venue"],"Le Mem")
        self.assertFalse(out["publicationAllowed"])
        self.assertTrue(out["reviewRequired"])
        self.assertNotIn("latitude",out)
        self.assertNotIn("longitude",out)
        classified=triage.triage(out,catalogue=published)
        self.assertEqual(classified["reviewBucket"],"already_catalogued")
        self.assertEqual(classified["catalogueMatches"],
                         ["go-c-20261118-rennes-marillion-lazuli"])
        self.assertFalse(classified["publicationAllowed"])

    def test_howlin_jaws_eight_existing_venues_are_review_only(self):
        checks = [
            ("Roubaix", "Cave aux Poètes", "la-cave-aux-poetes-roubaix"),
            ("PARIS", "Trabendo", "le-trabendo-paris"),
            ("BREST", "Carène", "la-carene-brest"),
            ("Rennes", "MeM", "le-mem-rennes"),
            ("ANGERS", "Chabada", "le-chabada-angers"),
            ("SAINT-ÉTIENNE", "Fil", "le-fil-saint-etienne"),
            ("STRASBOURG", "Laiterie", "la-laiterie-strasbourg"),
            ("NANCY", "Autre Canal", "l-autre-canal-nancy"),
        ]
        originals = [
            {"candidateId": "howlin-alias-" + str(i),
             "artistId": "howlin-jaws", "city": city, "venue": venue,
             "publicationAllowed": False, "reviewRequired": True,
             "newVenueToReview": True}
            for i, (city, venue, _) in enumerate(checks)
        ]
        reviewed, hits = hints.annotate(originals, CATALOG, hints.load())
        self.assertEqual(len(hits), 8)
        for baseline, row, (city, venue, canonical_id) in zip(originals, reviewed, checks):
            self.assertEqual(row["candidateId"], baseline["candidateId"])
            self.assertEqual(row["city"], city)
            self.assertEqual(row["venue"], venue)
            self.assertEqual(row["venueIdIfKnown"], canonical_id)
            self.assertFalse(row["newVenueToReview"])
            self.assertEqual(row["venueReconciliation"]["status"], "review_only")
            self.assertTrue(row["venueAddressToVerify"])
            self.assertTrue(row["coordinatesToVerify"])
            self.assertTrue(row["reviewRequired"])
            self.assertFalse(row["publicationAllowed"])
            self.assertNotIn("latitude", row)
            self.assertNotIn("longitude", row)

        # Une autre ville ou une salle homonyme ne profite pas de l'alias.
        rogue = dict(originals[0], candidateId="rogue", city="Paris")
        changed, matched = hints.annotate([rogue], CATALOG, hints.load())
        self.assertEqual(matched, [])
        self.assertNotIn("venueIdIfKnown", changed[0])

    def test_four_howlin_venue_leads_have_official_proofs_but_no_publication(self):
        national = json.loads(Path(__file__).with_name(
            "venues-national.json").read_text(encoding="utf-8"))
        discovery = json.loads(Path(__file__).with_name(
            "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(national["counts"].values()), len(national["venues"]))
        names = ("Marché Gare", "Salle Cap Caval", "6MIC", "Stereolux")
        for name in names:
            national_rows = [x for x in national["venues"] if x["name"] == name]
            source_rows = [x for x in discovery["venues"] if x["name"] == name]
            self.assertEqual(len(national_rows), 1, name)
            self.assertEqual(len(source_rows), 1, name)
            national_row, source_row = national_rows[0], source_rows[0]
            self.assertEqual(national_row["sourceType"], "official")
            self.assertFalse(national_row["enabled"])
            self.assertFalse(source_row["publish_automatically"])
            self.assertEqual(national_row["verifiedAt"], "2026-11-05")
            self.assertEqual(source_row["verifiedOn"], "2026-11-05")
            self.assertTrue(national_row["verifiedAgendaUrl"].startswith("https://"))
            self.assertTrue(source_row["officialAgendaUrl"].startswith("https://"))
            self.assertEqual(national_row["confirmedEventDate"][:4], "2026"
                             if name in ("Marché Gare", "Stereolux") else "2027")
            self.assertNotIn("latitude", national_row)
            self.assertNotIn("longitude", national_row)
            self.assertIn("collecteur", source_row["adapterStatus"].casefold())
        for name in ("Marché Gare", "Salle Cap Caval", "6MIC"):
            item = next(x for x in national["venues"] if x["name"] == name)
            self.assertTrue(item["officialAddress"].strip())
            self.assertTrue(item["addressEvidenceUrl"].startswith("https://"))

    def test_howlin_jaws_three_recently_published_venue_aliases(self):
        cases = [
            ("2027-02-27", "PENMARC'H", "Cap Caval", "salle-cap-caval-penmarch"),
            ("2026-12-08", "NANTES", "Stereolux", "stereolux-nantes"),
            ("2027-04-02", "Aix-En-Provence", "6MIC", "6mic-aix-en-provence"),
        ]
        raw = [
            {"candidateId": "artist-tour:alias-" + str(i), "artistId": "howlin-jaws",
             "date": date, "city": city, "venue": venue, "name": "Howlin' Jaws",
             "leadArtist": "Howlin' Jaws",
             "sourceUrl": "https://radical-production.fr/artistes/howlin-jaws/",
             "reviewRequired": True, "publicationAllowed": False,
             "newVenueToReview": True}
            for i, (date, city, venue, _) in enumerate(cases)
        ]
        output, hits = hints.annotate(raw, CATALOG, hints.load())
        self.assertEqual(len(hits), 3)
        for original, row, (_, city, venue, canonical) in zip(raw, output, cases):
            with self.subTest(alias=venue):
                self.assertEqual(row["candidateId"], original["candidateId"])
                self.assertEqual(row["venue"], venue)
                self.assertEqual(row["city"], city)
                self.assertEqual(row["venueIdIfKnown"], canonical)
                self.assertEqual(row["venueReconciliation"]["status"], "review_only")
                self.assertFalse(row["newVenueToReview"])
                self.assertTrue(row["reviewRequired"])
                self.assertFalse(row["publicationAllowed"])
                self.assertNotIn("latitude", row)
                self.assertNotIn("longitude", row)
        # Un homonyme en mauvaise ville reste inconnu.
        invalid = dict(raw[0], city="Paris", candidateId="artist-tour:wrong-city")
        out, matched = hints.annotate([invalid], CATALOG, hints.load())
        self.assertEqual(matched, [])
        self.assertNotIn("venueIdIfKnown", out[0])

    def test_document_prive_et_source_officielle(self):
        # Pour la CI du dépôt privé, la vraie configuration doit être valide
        # sur le petit catalogue témoin.
        real = hints.load()
        self.assertEqual(real["schema"], hints.SCHEMA)
        self.assertEqual(len(real["hints"]), 20)
        self.assertEqual(len(hints.validate_hints(real, CATALOG)), 20)


if __name__ == "__main__":
    unittest.main()
