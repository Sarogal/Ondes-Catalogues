"""No-network adversarial tests for predictable, bounded national rotation."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import rotating_batch

TODAY = date(2026, 11, 9)


class RotatingEvidenceBatchTests(unittest.TestCase):
    def test_four_slots_cover_all_32_eligible_candidates(self):
        leads = list(range(32))
        windows = [rotating_batch(leads, TODAY, 15, slot) for slot in range(4)]
        self.assertEqual({pages for _, _, pages in windows}, {3})
        self.assertEqual({page for _, page, _ in windows}, {0, 1, 2})
        for selected, page, pages in windows:
            self.assertLessEqual(len(selected), 15)
            self.assertGreaterEqual(page, 0)
            self.assertLess(page, pages)
        self.assertEqual(set(x for selected, _, _ in windows for x in selected),
                         set(leads))
        self.assertEqual(sum(len(windows[i][0]) for i in range(3)), 32)

    def test_backlogs_over_four_batches_rotate_across_days(self):
        leads = list(range(137))
        reviewed = set()
        pages_seen = set()
        for i in range(4):
            day = TODAY + timedelta(days=i)
            for slot in range(4):
                batch, page, pages = rotating_batch(leads, day, 15, slot)
                self.assertEqual(pages, 10)
                self.assertLessEqual(len(batch), 15)
                self.assertTrue(all(item in leads for item in batch))
                reviewed.update(batch)
                pages_seen.add(page)
        self.assertEqual(reviewed, set(leads))
        self.assertEqual(pages_seen, set(range(10)))

    def test_reproducible_even_when_run_starts_late(self):
        leads = [f"uid-{i}" for i in range(75)]
        for slot in range(4):
            first = rotating_batch(leads, TODAY, 15, slot)
            self.assertEqual(first, rotating_batch(leads, TODAY, 15, slot))
            self.assertEqual(first[0], leads[first[1]*15:(first[1]+1)*15])
        # A delayed runner should use its configured cron slot, never wall time.

    def test_empty_or_small_backlog(self):
        self.assertEqual(rotating_batch([], TODAY, 15, 0), ([], 0, 0))
        for slot in range(4):
            batch, page, pages = rotating_batch(["one"], TODAY, 15, slot)
            self.assertEqual((batch, page, pages), (["one"], 0, 1))

    def test_never_exceed_verification_budget_or_accept_invalid_slots(self):
        for budget in (0, 16, -1, True, "15", 1.5):
            with self.subTest(budget=budget):
                with self.assertRaises(ValueError):
                    rotating_batch(list(range(30)), TODAY, budget, 0)
        for slot in (-1, 4, True, "0", 0.5):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):
                    rotating_batch(list(range(30)), TODAY, 15, slot)


if __name__ == "__main__":
    unittest.main()
