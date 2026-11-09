"""Three public-runner discovery passes/day: more coverage, same safety limits."""
import datetime as dt
import unittest
from unittest.mock import patch

import discover
import laiterie_adapter


TODAY = dt.date(2026, 11, 9)


def fake_download(url, **_):
    return "<html><main></main></html>", url


class MultiPassRotationTests(unittest.TestCase):
    def test_local_scan_windows_are_three_fixed_nonoverlapping_slots(self):
        self.assertEqual(discover.scan_slot_for_hour(8), 0)
        self.assertEqual(discover.scan_slot_for_hour(11), 0)
        self.assertEqual(discover.scan_slot_for_hour(14), 1)
        self.assertEqual(discover.scan_slot_for_hour(17), 1)
        self.assertEqual(discover.scan_slot_for_hour(21), 2)
        self.assertEqual(discover.scan_slot_for_hour(23), 2)
        for invalid in (-1, 24, None):
            with self.assertRaises(ValueError):
                discover.scan_slot_for_hour(invalid)

    def test_three_p2_cohorts_are_distinct_with_identical_per_run_quota(self):
        sources = {"venues": [{
            "name": f"Official Venue {i}",
            "url": f"https://official-{i}.example/agenda",
            "city": "Lyon", "department": "69",
            "priority": "P2",
        } for i in range(15)]}
        runs = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=fake_download), \
             patch.object(discover.feeds, "feed_links",
                          return_value={"ics": [], "rss": []}):
            for slot in (0, 1, 2):
                diag = []
                found = discover.scan_venues(
                    sources, set(), TODAY, diag, max_p2=5, scan_slot=slot)
                self.assertEqual(found, [])
                self.assertEqual(len(diag), 5)
                self.assertTrue(all("error" not in d for d in diag))
                runs.append({d["venue"] for d in diag})
        self.assertTrue(all(len(x) == 5 for x in runs))
        self.assertEqual(len(set.union(*runs)), 15)
        self.assertEqual(sum(len(x) for x in runs), 15)

    def test_laiterie_extra_agenda_page_rotates_same_day_without_extra_http(self):
        from laiterie_adapter import AGENDA
        source = {"name": "La Laiterie", "url": AGENDA,
                  "city": "Strasbourg", "department": "67",
                  "priority": "P1",
                  "adapter": "laiterie_official_detail_review",
                  "maxDetailPagesPerRun": 1}
        page_one = ('<html><main><a href="'
                    '/la-laiterie/programmation/page/4/">4</a></main></html>')
        observed = []
        def fake(url, **_):
            observed.append(url)
            return (page_one if url == AGENDA
                    else "<html><main></main></html>"), url
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=fake), \
             patch.object(discover.feeds, "feed_links",
                          return_value={"ics": [], "rss": []}):
            pages = []
            for slot in (0, 1, 2):
                observed.clear()
                info = []
                found = discover.scan_venues(
                    {"venues": [source]}, set(), TODAY, info, scan_slot=slot)
                self.assertEqual(found, [])
                self.assertEqual(len(info), 1)
                self.assertNotIn("error", info[0])
                self.assertEqual(info[0]["adapterDiagnostic"]["agendaPagesChecked"], 2)
                extra = [u for u in observed if
                         "/la-laiterie/programmation/page/" in u]
                self.assertEqual(len(extra), 1)
                pages.append(extra[0])
        self.assertEqual(len(set(pages)), 3)

    def test_unknown_slot_is_fail_closed(self):
        with self.assertRaises(ValueError):
            discover.scan_venues({"venues": []}, set(), TODAY, [], scan_slot=3)


if __name__ == "__main__":
    unittest.main()
