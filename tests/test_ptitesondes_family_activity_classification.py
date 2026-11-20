"""Pure, adversarial national family activity proposals; never publishes."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_family_national_scope import FAMILY_TYPES
from ptitesondes_family_activity_classification import (
    ACTIVITY_PATTERNS, propose_family_activity,
)


class FamilyActivityClassificationTests(unittest.TestCase):
    def test_all_fourteen_nonmusical_types_can_be_discovered_without_venue_lists(self):
        examples = {
            "lecture-jeunesse": "Lecture d'histoires pour enfants",
            "atelier-numerique": "Atelier de robotique pour enfants",
            "lecture-cinema": "Ciné-lecture pour enfants",
            "jeux-famille": "Jeux de société en famille",
            "atelier-creatif": "Atelier de poterie pour enfants",
            "atelier-sensoriel": "Parcours sensoriel pour bébés",
            "atelier-scientifique": "Atelier scientifique pour enfants",
            "spectacle-jeunesse": "Spectacle de marionnettes pour enfants",
            "cinema-jeunesse": "Séance cinéma en famille",
            "sortie-nature": "Balade nature en famille",
            "animaux-ferme": "Visite de ferme pour enfants",
            "musee-patrimoine": "Visite guidée du musée en famille",
            "fete-familiale": "Carnaval en famille",
            "activite-sportive": "Parcours de motricité pour enfants",
        }
        self.assertTrue(set(FAMILY_TYPES).issubset(examples))
        self.assertEqual(set(ACTIVITY_PATTERNS), set(examples))
        for key, title in examples.items():
            if key not in FAMILY_TYPES:
                continue
            with self.subTest(key=key):
                result = propose_family_activity(title, "")
                self.assertEqual(result["category_proposal"], key)
                self.assertEqual(
                    result["category_label_proposal"], FAMILY_TYPES[key][0])
                self.assertFalse(result["publication_ready"])
                self.assertTrue(result["requires_independent_event_proof"])
                self.assertEqual(result["public_writes"], 0)

    def test_sensory_category_activates_only_when_available_in_taxonomy(self):
        title = "Parcours sensoriel pour bébés"
        baseline = propose_family_activity(title, "")
        if "atelier-sensoriel" not in FAMILY_TYPES:
            self.assertEqual(baseline["category_proposal"], None)
        with patch.dict(FAMILY_TYPES, {"atelier-sensoriel":
                                     ("Atelier sensoriel", "atelier")}):
            activated = propose_family_activity(title, "")
            self.assertEqual(activated["category_proposal"], "atelier-sensoriel")
            self.assertFalse(activated["publication_ready"])
            self.assertEqual(activated["public_writes"], 0)

    def test_title_without_juvenile_evidence_is_never_authorized(self):
        candidate = propose_family_activity("Atelier de peinture", "")
        self.assertEqual(candidate["decision"], "no_explicit_family_audience_cue")
        self.assertIsNone(candidate["category_proposal"])

    def test_detailed_activity_in_description_is_usable_as_proposal_only(self):
        result = propose_family_activity(
            "Les petits explorateurs",
            "Pour enfants : atelier de poterie en médiathèque.")
        self.assertEqual(result["category_proposal"], "atelier-creatif")
        self.assertTrue(result["official_source_not_verified"])
        self.assertTrue(result["location_not_verified"])

    def test_adult_exclusion_overrides_audience_word(self):
        for body in (
            "Pour enfants, mais réservé aux adultes",
            "Interdit aux enfants",
            "Adultes uniquement : même si les enfants sont évoqués",
        ):
            with self.subTest(body=body):
                result = propose_family_activity(
                    "Atelier de peinture pour enfants", body)
                self.assertIsNone(result["category_proposal"])
                self.assertEqual(
                    result["decision"], "adult_only_or_contradictory_audience")

    def test_ambiguous_two_explicit_activity_categories_defer(self):
        result = propose_family_activity(
            "Atelier scientifique et atelier de poterie pour enfants", "")
        self.assertIsNone(result["category_proposal"])
        self.assertEqual(result["decision"], "ambiguous_activity_category")

    def test_unclassified_activity_is_not_guessed_from_family_cue(self):
        result = propose_family_activity(
            "Atelier spécial pour enfants", "Animation pour toute la famille")
        self.assertIsNone(result["category_proposal"])
        self.assertEqual(result["decision"], "activity_type_not_established")

    def test_existing_musical_formats_keep_their_existing_path(self):
        for title in (
            "Concert jeune public et atelier de poterie",
            "Conte musical et atelier de peinture pour enfants",
            "Éveil musical et parcours sensoriel pour bébés",
        ):
            with self.subTest(title=title):
                result = propose_family_activity(title, "")
                self.assertEqual(result["decision"], "existing_musical_path_only")
                self.assertIsNone(result["category_proposal"])

    def test_no_proposal_can_grant_publication_or_reach_publisher(self):
        with patch("merge_policy.merge", side_effect=AssertionError(
                "publisher must not be called")):
            result = propose_family_activity(
                "Visite de ferme pour enfants", "En famille")
        self.assertFalse(result["publication_ready"])
        self.assertTrue(result["audience_claim_not_verified"])
        self.assertTrue(result["official_source_not_verified"])
        self.assertTrue(result["licence_not_verified"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)
        self.assertNotIn("events", result)

    def test_malformed_or_oversize_input_fails_closed(self):
        for title, desc in (
            (None, ""), (45, "famille"), ("", "pour enfants"),
            ("Atelier de peinture pour enfants", None),
            ("X" * 301, "pour enfants"),
            ("Atelier de peinture pour enfants", "x" * 5001),
        ):
            with self.subTest(title=str(title)[:15]):
                result = propose_family_activity(title, desc)
                self.assertEqual(result["decision"], "invalid_activity_text")
                self.assertIsNone(result["category_proposal"])


if __name__ == "__main__":
    unittest.main()
