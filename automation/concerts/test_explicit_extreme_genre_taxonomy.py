"""New underground genre aliases are discoverable, never publishable evidence.

These are synthetic offline cases, not confirmed real-world concerts.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import triage


EXPLICIT_EXTREME_GENRES = (
    "Grindcore",
    "Mathcore",
    "Powerviolence",
    "Screamo",
    "Skramz",
    "Blackgaze",
    "D-beat",
)


class ExplicitExtremeGenreTaxonomyTests(unittest.TestCase):
    def setUp(self):
        self.empty_catalogue = {"artists": [], "venues": [], "events": []}

    def test_new_labels_reach_review_only_in_both_engines(self):
        for label in EXPLICIT_EXTREME_GENRES:
            with self.subTest(label=label):
                self.assertIsNotNone(discover.GENRE.search(label))
                row = triage.triage({
                    "source": "agenda_officiel_structuré",
                    "name": "Line-up to verify",
                    "date": "2027-02-21",
                    "city": "Lille",
                    "classification": [label],
                }, catalogue=self.empty_catalogue)
                self.assertEqual(row["genreEvidence"], "tag_genre_source")
                self.assertEqual(row["reviewBucket"], "genre_tag_review")
                self.assertIs(row["publicationAllowed"], False)
                self.assertIs(row["reviewRequired"], True)
                self.assertNotIn("newArtists", row)

    def test_rock_generic_and_pop_do_not_become_explicit_extreme_genres(self):
        for label in ("Rock", "Indie Rock", "Pop", "Jazz", "Folk", "Electro"):
            with self.subTest(label=label):
                self.assertIsNone(discover.GENRE.search(label))
                self.assertIsNone(triage.genre_evidence({"classification": [label]}))

    def test_biography_and_venue_reputation_are_not_event_genre_proof(self):
        row = triage.triage({
            "name": "Line-up to verify",
            "date": "2027-02-21",
            "city": "Lille",
            "sourceConfidence": "venue also hosts powerviolence and screamo",
            "biography": "artist previously played blackgaze",
            "classification": [],
        }, catalogue=self.empty_catalogue)
        self.assertEqual(row["reviewBucket"], "genre_unknown")
        self.assertIs(row["publicationAllowed"], False)

    def test_cancelled_and_undated_remain_held_regardless_of_label(self):
        examples = (
            ({"cancellationNotice": True, "date": "2027-02-21"},
             "cancellation_watch"),
            ({"date": None}, "undated_lead"),
        )
        for extra, bucket in examples:
            with self.subTest(bucket=bucket):
                row = triage.triage({
                    "name": "Line-up to verify",
                    "date": "2027-02-21",
                    "city": "Lille",
                    "classification": ["Grindcore"],
                    **extra,
                }, catalogue=self.empty_catalogue)
                self.assertEqual(row["reviewBucket"], bucket)
                self.assertIs(row["publicationAllowed"], False)


if __name__ == "__main__":
    unittest.main()
