"""Keep two collector mirrors from consuming two independent verification slots."""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import (
    unique_review_candidates, rotating_batch, evaluate
)

TODAY = date(2026, 11, 9)
CANONICAL = (
    "https://openagenda.com/bibliotheques-de-marseille/events/eveil-musical-8687467"
)
ALIAS = (
    "https://openagenda.com/bibliotheques-de-territoire-marseille/events/"
    "24285475_eveil-musical-8687467"
)


def lead(collector="opendatasoft-index", **changes):
    result = {
        "external_id": "24285475", "collector": collector,
        "title": "Éveil musical", "city": "Marseille",
        "venue": "Bibliothèque des Cinq-Avenues",
        "source_url": CANONICAL if collector == "opendatasoft-index" else ALIAS,
        "date_start": "2026-11-27", "date_end": "2026-11-27"
    }
    result.update(changes)
    return result


class DuplicatedCollectorEvidenceTests(unittest.TestCase):
    def test_prefers_exact_index_canonical_and_never_counts_as_second_proof(self):
        raw = [lead("openagenda-v2"), lead()]
        selected, eligible, dropped, conflicts = unique_review_candidates(raw, TODAY)
        self.assertEqual((eligible, dropped, conflicts), (2, 1, 0))
        self.assertEqual(selected, [lead()])
        self.assertEqual(
            {x["source_url"] for x in selected}, {CANONICAL})
        self.assertEqual(
            [rotating_batch(selected, TODAY, 15, slot)[0] for slot in range(4)],
            [selected]*4)
        self.assertNotIn("verified_at", selected[0])

    def test_two_distinct_sessions_from_four_collector_rows(self):
        a = lead()
        b = lead("openagenda-v2")
        other = {
            "external_id": "9414326", "title": "Éveil musical",
            "date_start": "2026-12-19", "date_end": "2026-12-19",
            "city": "Marseille", "venue": "Bibliothèque des Cinq-Avenues"
        }
        c = lead(**dict(other, source_url=(
            "https://openagenda.com/bibliotheques-de-marseille/events/"
            "eveil-musical-5625656")))
        d = lead("openagenda-v2", **dict(other, source_url=(
            "https://openagenda.com/bibliotheques-de-territoire-marseille/"
            "events/9414326_eveil-musical-5625656")))
        selected, eligible, dropped, conflicts = unique_review_candidates(
            [a, b, c, d], TODAY)
        self.assertEqual((eligible, dropped, conflicts), (4, 2, 0))
        self.assertEqual(len(selected), 2)
        self.assertEqual([x["date_start"] for x in selected],
                         ["2026-11-27", "2026-12-19"])
        self.assertTrue(all(x["collector"] == "opendatasoft-index"
                            for x in selected))

    def test_same_uid_on_nonconsecutive_dates_is_not_fused(self):
        a = lead()
        another = lead(date_start="2026-12-19", date_end="2026-12-19")
        selected, eligible, dropped, conflicts = unique_review_candidates(
            [another, a], TODAY)
        self.assertEqual((eligible, dropped, conflicts), (2, 0, 0))
        self.assertEqual(len(selected), 2)

    def test_conflicting_title_or_location_defers_whole_uid_day(self):
        for change in (
            {"title": "Spectacle différent"},
            {"venue": "Médiathèque Salim-Hatubou"},
            {"city": "Pacé", "venue": "Totems"},
        ):
            with self.subTest(conflict=change):
                selected, eligible, dropped, conflicts = unique_review_candidates(
                    [lead(), lead("openagenda-v2", **change)], TODAY)
                self.assertEqual((eligible, dropped, conflicts), (2, 0, 1))
                self.assertEqual(selected, [])

    def test_two_conflicting_urls_from_one_collector_must_not_pick_one(self):
        conflicting = lead(source_url=CANONICAL.replace(
            "eveil-musical-8687467", "eveil-musical-999999"))
        selected, eligible, dropped, conflicts = unique_review_candidates(
            [lead(), conflicting], TODAY)
        self.assertEqual((eligible, dropped, conflicts), (2, 0, 1))
        self.assertEqual(selected, [])

    def test_exact_duplicate_of_same_source_is_reduced(self):
        selected, eligible, dropped, conflicts = unique_review_candidates(
            [lead(), lead()], TODAY)
        self.assertEqual((eligible, dropped, conflicts), (2, 1, 0))
        self.assertEqual(selected, [lead()])

    def test_unreviewed_location_or_outdated_session_stays_ineligible(self):
        rows = [
            lead(),
            lead(city="Marseille", venue="Bibliothèque du Merlan"),
            lead(date_start="2026-11-08", date_end="2026-11-08"),
            lead(source_url=CANONICAL + "?preview=true")
        ]
        selected, eligible, dropped, conflicts = unique_review_candidates(
            rows, TODAY)
        self.assertEqual((eligible, dropped, conflicts), (1, 0, 0))
        self.assertEqual(selected, [lead()])

    def test_determinism_does_not_depend_on_collector_arrival_order(self):
        input_rows = [lead("openagenda-v2"), lead()]
        forward = unique_review_candidates(input_rows, TODAY)
        reverse = unique_review_candidates(list(reversed(input_rows)), TODAY)
        self.assertEqual(forward, reverse)


if __name__ == "__main__":
    unittest.main()
