"""Daily bounded official collectors cover rotated batches with safe stability.

The agenda may change over time and previously published URLs are still
handled separately. The test only checks stable lists and the same daily cap.
"""
import datetime as dt
import unittest

import bateau_ivre_adapter
import undercovered_official_adapter
import echonova_adapter


class DailyOfficialBatchRotationTests(unittest.TestCase):
    def test_daily_rotation_scans_both_halves_without_duplicate(self):
        day = dt.date(2026, 11, 4)
        yesterday = day.isoformat()
        tomorrow = (day + dt.timedelta(days=1)).isoformat()
        urls = [
            [bateau_ivre_adapter.BASE +
             f"/%C3%A9v%C3%A8nements/official-band-{i:02d}/"
             for i in range(12)],
            [undercovered_official_adapter.GRILLEN +
             "/programmation/official-band-%02d" % i
             for i in range(12)],
            [echonova_adapter.BASE + "/evenement/official-band-%02d/" % i
             for i in range(12)],
        ]
        for adapter, official_urls in zip((
                bateau_ivre_adapter, undercovered_official_adapter,
                echonova_adapter), urls):
            with self.subTest(adapter=adapter.__name__):
                a = adapter.select_urls(official_urls, set(), yesterday, limit=6)
                b = adapter.select_urls(official_urls, set(), tomorrow, limit=6)
                self.assertEqual(len(a), 6)
                self.assertEqual(len(b), 6)
                if adapter is bateau_ivre_adapter:
                    # Bateau Ivre intentionally keeps two first-party
                    # details in the interday recheck core. The three daily
                    # slots cover the remaining pages instead of pretending
                    # same-day repeats are independent confirmations.
                    self.assertGreaterEqual(len(set(a) & set(b)), 2)
                    self.assertGreaterEqual(len(set(a) | set(b)), 10)
                else:
                    self.assertFalse(set(a) & set(b),
                                     "Other collectors must visit the other half")
                    self.assertEqual(set(a) | set(b), set(official_urls))
                self.assertEqual(
                    len(adapter.select_urls(official_urls, set(), tomorrow,
                                            limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
