"""Tests offline du classement des annonces — jamais de publication."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage


class TriageTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = {
            "artists": [{"id": "death-valley-girls", "name": "Death Valley Girls"},
                        {"id": "others", "name": "Bella and the Bizarre"}],
            "venues": [{"id": "paloma", "city": "Nîmes"}],
            "events": [{
                "id": "existing-1113", "date": "2026-11-13",
                "title": "Death Valley Girls + Bella and the Bizarre",
                "venueId": "paloma", "artistIds": ["death-valley-girls", "others"]
            }],
        }

    def test_duplicate_ics_title_differs_in_case(self):
        row = triage.triage({
            "source": "agenda_ics", "name": "DEATH VALLEY GIRLS + BELLA AND THE BIZARRE",
            "date": "2026-11-13", "city": "Nîmes"
        }, catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "possible_duplicate")
        self.assertEqual(row["catalogueMatches"], ["existing-1113"])
        self.assertFalse(row["publicationAllowed"])

    def test_soen_titre_court_avec_premiere_partie(self):
        catalog = {
            "venues": [{"id": "rex", "city": "Toulouse"}],
            "artists": [{"id": "soen", "name": "Soen"}],
            "events": [{"id": "event-soen", "date": "2026-12-03",
                        "title": "Soen", "venueId": "rex", "artistIds": ["soen"]}],
        }
        candidate = {"date": "2026-12-03", "city": "Toulouse",
                     "name": "Soen + Tribulation"}
        result = triage.triage(candidate, catalogue=catalog)
        self.assertEqual(result["reviewBucket"], "possible_duplicate")
        self.assertEqual(result["catalogueMatches"], ["event-soen"])

    def test_no_duplicate_different_date(self):
        row = triage.triage({
            "source": "agenda_ics", "name": "Death Valley Girls",
            "date": "2026-11-14", "city": "Nîmes"
        }, catalogue=self.catalogue)
        self.assertFalse(row["possibleExistingConcert"])

    def test_cancelled_prioritized_as_watch_not_new_concert(self):
        row = triage.triage({
            "source": "ics_cancellation_notice",
            "name": "CONCERT METAL ANNULÉ", "date": "2026-11-25",
            "city": "Paris", "cancellationNotice": True
        }, catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "cancellation_watch")
        self.assertFalse(row["publicationAllowed"])

    def test_rss_never_gets_fabricated_date(self):
        row = triage.triage({
            "source": "actualite_rss_non_datee",
            "name": "Marillion annonce une tournée",
            "date": None, "city": "Nîmes"
        }, catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "undated_lead")
        self.assertIsNone(row["date"])

    def test_genre_only_if_event_classification(self):
        assert triage.genre_evidence({"classification": ["Metal", "Hard Rock"]})
        self.assertIsNone(triage.genre_evidence({
            "sourceConfidence": "Salle spécialisée métal punk, genre de l'événement inconnu"
        }))

    def test_stoner_category_marked_for_review_not_publication(self):
        row = triage.triage({"source": "agenda_officiel_rex_genre",
                            "date": "2026-11-05", "city": "Toulouse",
                            "name": "7WEEKS & Guest",
                            "classification": ["rock", "stoner"]},
                           catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "genre_tag_review")
        self.assertFalse(row["publicationAllowed"])

    def test_specifically_named_official_rock_subgenres_enter_review_only(self):
        examples = [
            "heavy rock", "garage rock", "post-rock", "noise rock",
            "électro rock", "math rock", "psych rock", "shoegaze", "grunge",
        ]
        for label in examples:
            with self.subTest(label=label):
                row = triage.triage({
                    "source": "agenda_officiel_chatodo_detail_review",
                    "date": "2026-12-03", "city": "Blois",
                    "name": "Concert groupe", "classification": [label],
                }, catalogue=self.catalogue)
                self.assertEqual(row["reviewBucket"], "genre_tag_review")
                self.assertEqual(row["genreEvidence"], "tag_genre_source")
                self.assertFalse(row["publicationAllowed"])
                self.assertTrue(row["reviewRequired"])

    def test_official_event_rock_review_only_vs_menu_biography(self):
        candidate = {
            "date": "2026-12-16", "city": "Rennes", "name": "Hanry",
            "classification": ["Rock"],
            "genreEvidenceScope": "official_event_card",
            "officialDetailFound": True,
            "sourceUrl": "https://antipode-rennes.fr/agenda/hanry-2026",
        }
        row = triage.triage(candidate, catalogue=self.catalogue)
        self.assertEqual(row["genreEvidence"], "official_event_rock_tag")
        self.assertEqual(row["reviewBucket"], "genre_tag_review")
        self.assertTrue(row["reviewRequired"])
        self.assertFalse(row["publicationAllowed"])
        for scope, verified in (
            ("venue_category_menu", True), ("artist_biography", True),
            ("unknown", True), ("official_event_card", False),
        ):
            with self.subTest(scope=scope, verified=verified):
                uncertain = {**candidate, "genreEvidenceScope": scope,
                             "officialDetailFound": verified}
                row = triage.triage(uncertain, catalogue=self.catalogue)
                self.assertIsNone(row["genreEvidence"])
                self.assertEqual(row["reviewBucket"], "genre_unknown")
                self.assertFalse(row["publicationAllowed"])

    def test_generic_rock_and_venue_biography_still_not_genre_evidence(self):
        for label in ("Rock", "Pop Rock", "Rock alternatif à confirmer",
                      "Électro", "Rap", "Folk"):
            with self.subTest(label=label):
                row = triage.triage({
                    "date": "2027-01-15", "city": "Tours",
                    "name": "Concert sans genre vérifié",
                    "classification": [label],
                    "sourceConfidence": "Le lieu accueille du heavy rock et du métal",
                }, catalogue=self.catalogue)
                self.assertEqual(row["reviewBucket"], "genre_unknown")
                self.assertFalse(row["publicationAllowed"])

    def test_atelier_excluded_even_if_date(self):
        row = triage.triage({
            "date": "2027-01-20", "name": "Wikipaloma : Communiquer son projet",
            "city": "Nîmes"
        }, catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "excluded_nonconcert")

    def test_festival_never_added_as_concert(self):
        row = triage.triage({
            "date": "2027-04-20", "name": "One Way Out Fest IV", "city": "Lyon"
        }, catalogue=self.catalogue)
        self.assertEqual(row["reviewBucket"], "festival_overlap_review")


    def test_exact_venue_artist_day_is_already_catalogued_even_city_differs(self):
        reference = {
            "artists": [{"id": "marillion", "name": "Marillion"},
                        {"id": "lazuli", "name": "Lazuli"}],
            "venues": [{"id": "le-bikini-toulouse", "name": "Le Bikini",
                        "city": "Ramonville-Saint-Agne"}],
            "events": [{
                "id": "go-existing-marillion", "date": "2026-11-25",
                "title": "Marillion + Lazuli",
                "artistIds": ["marillion", "lazuli"],
                "venueId": "le-bikini-toulouse",
            }],
        }
        item = {
            "source": "artist_official_tour_listing",
            "artistId": "marillion", "name": "Marillion",
            "leadArtist": "Marillion", "date": "2026-11-25",
            "venue": "Le Bikini", "city": "Toulouse",
            "venueIdIfKnown": "le-bikini-toulouse",
        }
        result = triage.triage(item, catalogue=reference)
        self.assertEqual(result["reviewBucket"], "already_catalogued")
        self.assertEqual(result["catalogueMatches"], ["go-existing-marillion"])
        self.assertEqual(result["catalogueMatchEvidence"],
                         "exact-date-venue-id-artist-id")
        self.assertTrue(result["reviewRequired"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["city"], "Toulouse")
        self.assertNotIn("newArtists", result)
        ordered, shortlist, counts = triage.classify([item], reference)
        self.assertEqual(len(ordered), 1)
        self.assertEqual(shortlist, [])
        self.assertEqual(counts["already_catalogued"], 1)

    def test_exact_identity_not_guessed_for_other_venue_artist_or_day(self):
        reference = {
            "artists": [{"id": "marillion", "name": "Marillion"}],
            "venues": [
                {"id": "bikini", "name": "Le Bikini", "city": "Ramonville-Saint-Agne"},
                {"id": "rex", "name": "Le Rex", "city": "Toulouse"},
            ],
            "events": [{"id": "known", "date": "2026-11-25",
                        "title": "Marillion", "artistIds": ["marillion"],
                        "venueId": "bikini"}],
        }
        base = {"date": "2026-11-25", "city": "Toulouse",
                "name": "Marillion", "leadArtist": "Marillion",
                "artistId": "marillion", "venueIdIfKnown": "bikini"}
        for altered in ({"venueIdIfKnown": "rex"},
                        {"artistId": "different"},
                        {"date": "2026-11-26"},
                        {"venueIdIfKnown": None},
                        {"artistId": None}):
            with self.subTest(altered=altered):
                row = triage.triage(dict(base, **altered), catalogue=reference)
                self.assertNotEqual(row["reviewBucket"], "already_catalogued")
                self.assertIsNone(row["catalogueMatchEvidence"])
                self.assertFalse(row["publicationAllowed"])

    def test_cancellation_same_date_venue_artist_always_prioritized(self):
        row = {
            "artistId": "death-valley-girls",
            "date": "2026-11-13", "city": "Nîmes",
            "name": "Death Valley Girls",
            "venueIdIfKnown": "paloma", "cancellationNotice": True,
        }
        checked = triage.triage(row, catalogue=self.catalogue)
        self.assertEqual(checked["reviewBucket"], "cancellation_watch")
        self.assertEqual(checked["catalogueMatches"], ["existing-1113"])
        self.assertFalse(checked["publicationAllowed"])

    def test_classification_and_shortlist(self):
        rows = [
            {"source": "agenda_ics", "date": "2026-11-13", "city": "Nîmes",
             "name": "Death Valley Girls + Bella and the Bizarre"},
            {"source": "agenda_ics", "date": "2027-01-01", "city": "Nîmes",
             "name": "Aucun artiste identifié"},
            {"source": "ticketmaster_api", "date": "2027-03-03", "city": "Lyon",
             "name": "Show", "classification": ["Metal"]},
            {"source": "actualite_rss_non_datee", "date": None, "city": "Lyon",
             "name": "Nouvelle générale"},
        ]
        ordered, shortlist, counts = triage.classify(rows, self.catalogue)
        self.assertEqual(len(ordered), 4)
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(counts["possible_duplicate"], 1)
        self.assertEqual(counts["genre_tag_review"], 1)
        self.assertTrue(all(x["publicationAllowed"] is False for x in ordered))


if __name__ == "__main__":
    unittest.main()
