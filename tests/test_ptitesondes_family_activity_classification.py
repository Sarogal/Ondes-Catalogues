"""Offline adversarial checks for P'tites Ondes' radio-centric scope."""
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


class RadioEditorialScopeTests(unittest.TestCase):
    def test_narrow_scope_does_not_inherit_all_general_leisure_types(self):
        self.assertEqual(set(ACTIVITY_PATTERNS), {
            "lecture-jeunesse", "spectacle-jeunesse",
        })
        self.assertTrue(set(ACTIVITY_PATTERNS).issubset(FAMILY_TYPES))
        self.assertNotIn("sortie-nature", ACTIVITY_PATTERNS)
        self.assertNotIn("jeux-famille", ACTIVITY_PATTERNS)

    def test_storytelling_and_youth_shows_are_discoverable(self):
        samples = {
            "Lecture d'histoires pour enfants": "lecture-jeunesse",
            "Heure du conte en famille": "lecture-jeunesse",
            "Conte pour enfants": "lecture-jeunesse",
            "Spectacle de marionnettes pour enfants": "spectacle-jeunesse",
            "Spectacle de magie en famille": "spectacle-jeunesse",
            "Théâtre jeune public": "spectacle-jeunesse",
            "Spectacle jeune public": "spectacle-jeunesse",
        }
        for title, expected in samples.items():
            with self.subTest(title=title):
                result = propose_family_activity(title, "")
                self.assertEqual(result["category_proposal"], expected)
                self.assertEqual(
                    result["category_label_proposal"], FAMILY_TYPES[expected][0])
                self.assertFalse(result["publication_ready"])
                self.assertTrue(result["requires_independent_event_proof"])
                self.assertEqual(result["public_writes"], 0)

    def test_radio_scope_excludes_generic_family_outings(self):
        samples = (
            "Goûter au parc pour enfants",
            "Pique-nique des familles",
            "Parcours de motricité pour enfants",
            "Balade nature en famille",
            "Visite de ferme pour enfants",
            "Visite du musée en famille",
            "Jeux de société en famille",
            "Atelier scientifique pour enfants",
            "Atelier de poterie pour enfants",
            "Séance cinéma en famille",
            "Carnaval en famille",
            "Parcours sensoriel pour bébés",
            "Atelier de robotique pour enfants",
        )
        for title in samples:
            with self.subTest(title=title):
                output = propose_family_activity(title, "")
                self.assertIsNone(output["category_proposal"])
                self.assertEqual(output["decision"], "out_of_radio_editorial_scope")

    def test_unknown_venue_does_not_appear_in_editorial_logic(self):
        result = propose_family_activity(
            "Spectacle jeune public",
            "Un spectacle pour enfants dans une place de village sans numéro.")
        self.assertEqual(result["category_proposal"], "spectacle-jeunesse")
        self.assertTrue(result["location_not_verified"])
        self.assertFalse(result["publication_ready"])

    def test_named_work_can_use_verified_description_later(self):
        result = propose_family_activity(
            "Le petit voyageur",
            "Spectacle de marionnettes jeune public, dès 3 ans.")
        self.assertEqual(result["category_proposal"], "spectacle-jeunesse")
        self.assertTrue(result["official_source_not_verified"])

    def test_title_without_explicit_family_cue_is_held_for_review(self):
        result = propose_family_activity("Spectacle de magie", "")
        self.assertEqual(result["decision"], "no_explicit_family_audience_cue")
        self.assertIsNone(result["category_proposal"])

    def test_mixed_storytelling_and_show_is_not_guessed(self):
        result = propose_family_activity(
            "Spectacle de marionnettes et heure du conte pour enfants", "")
        self.assertEqual(result["decision"], "ambiguous_activity_category")
        self.assertIsNone(result["category_proposal"])

    def test_musical_formats_remain_in_historical_pipeline(self):
        for title in (
            "Concert jeune public", "Conte musical pour enfants",
            "Éveil musical pour bébés", "Spectacle musical pour enfants",
            "Atelier sonore pour enfants",
        ):
            with self.subTest(title=title):
                result = propose_family_activity(title, "")
                self.assertEqual(result["decision"], "existing_musical_path_only")
                self.assertIsNone(result["category_proposal"])

    def test_adult_only_overrides_child_cues(self):
        result = propose_family_activity(
            "Spectacle jeune public", "Réservé aux adultes, enfants interdits")
        self.assertEqual(result["decision"], "adult_only_or_contradictory_audience")
        self.assertIsNone(result["category_proposal"])

    def test_no_classifier_path_can_reach_publisher(self):
        with patch("merge_policy.merge", side_effect=AssertionError(
                "publisher must not be called")):
            result = propose_family_activity("Heure du conte pour enfants", "")
        self.assertFalse(result["publication_ready"])
        self.assertTrue(result["audience_claim_not_verified"])
        self.assertTrue(result["official_source_not_verified"])
        self.assertTrue(result["licence_not_verified"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)
        self.assertNotIn("events", result)

    def test_invalid_text_fails_closed(self):
        for title, desc in (
            (None, ""), (45, "famille"), ("", "pour enfants"),
            ("Spectacle jeune public", None),
            ("X" * 301, "pour enfants"),
            ("Spectacle jeune public", "x" * 5001),
        ):
            with self.subTest(title=str(title)[:15]):
                r = propose_family_activity(title, desc)
                self.assertEqual(r["decision"], "invalid_activity_text")
                self.assertIsNone(r["category_proposal"])


if __name__ == "__main__":
    unittest.main()
