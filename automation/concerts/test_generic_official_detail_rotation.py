"""Regression: rotate all first-party venue links without extra requests."""
from __future__ import annotations

import datetime as dt
import unittest

import discover


class GenericVenueLinkRotationTests(unittest.TestCase):
    def test_three_slots_cover_entire_first_party_programme(self):
        day = dt.date(2026, 11, 19)
        links = [
            "https://official.example/evenement/metal-night-%02d/" % i
            for i in range(14)]
        visited = set()
        for delta in (0, 1):
            for slot in (0, 1, 2):
                selection = discover.select_generic_official_detail_links(
                    links, day + dt.timedelta(days=delta), slot)
                self.assertLessEqual(len(selection), 3)
                self.assertEqual(len(selection), len(set(selection)))
                visited.update(selection)
        self.assertEqual(visited, set(links))

    def test_never_beyond_three_per_day_and_deterministic(self):
        day = dt.date(2026, 11, 19)
        links = [str(i) for i in range(25)]
        for slot in (0, 1, 2):
            got = discover.select_generic_official_detail_links(
                links, day, slot, limit=3)
            self.assertEqual(len(got), 3)
            self.assertEqual(got, discover.select_generic_official_detail_links(
                links, day, slot, limit=3))
        short = discover.select_generic_official_detail_links(
            ["one", "two"], day, 0, limit=3)
        self.assertEqual(len(short), 2)
        self.assertEqual(set(short), {"one", "two"})

    def test_empty_duplicate_and_invalid_inputs(self):
        day = dt.date(2026, 11, 19)
        self.assertEqual(
            discover.select_generic_official_detail_links([], day, 0), [])
        self.assertEqual(
            len(discover.select_generic_official_detail_links(
                ["a", "a", "b"], day, 0)), 2)
        for bad_day, bad_slot, bad_limit in (
            (None, 0, 3),
            (dt.datetime(2026, 11, 19), 0, 3),
            (day, 3, 3),
            (day, -1, 3),
            (day, 0, 4),
            (day, 0, -1),
        ):
            with self.subTest(args=(bad_day, bad_slot, bad_limit)):
                with self.assertRaises(ValueError):
                    discover.select_generic_official_detail_links(
                        ["a"], bad_day, bad_slot, limit=bad_limit)

    def test_no_per_concert_allowlist_or_approval_is_generated(self):
        day = dt.date(2026, 11, 19)
        urls = ["/evenement/one/", "/evenement/two/"]
        snapshot = list(urls)
        chosen = discover.select_generic_official_detail_links(
            urls, day, 1)
        self.assertEqual(urls, snapshot)
        self.assertEqual(set(chosen), set(urls))
        self.assertTrue(all(isinstance(url, str) for url in chosen))


if __name__ == "__main__":
    unittest.main()
