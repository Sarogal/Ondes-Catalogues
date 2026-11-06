"""Offline preview tests: no Ferrailleur record can publish directly."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ferrailleur_preview as p
from test_ferrailleur_official import PAGE, candidate, catalogue


class FerrailleurDryRunTests(unittest.TestCase):
    def test_verified_live_shaped_fixture_is_always_preview_only(self):
        row = {"candidate": candidate(), "observations": 9}
        report = p.inspect({"items": {"a": row}}, catalogue(),
                           dt.date(2026, 11, 1),
                           fetch=lambda url, robots: PAGE)
        self.assertEqual(report["verifiedPreviewOnly"], 1)
        self.assertEqual(report["held"], 0)
        self.assertFalse(report["publicationAllowed"])
        self.assertTrue(all(r["publish"] is False for r in report["results"]))

    def test_unproven_and_single_observation_are_excluded(self):
        a = candidate();b = candidate()
        a["officialDetailFound"] = False
        report = p.inspect({"items": {"a":{"candidate": a,"observations":9},
                                       "b":{"candidate": b,"observations":1}}},
                           catalogue(),dt.date(2026,11,1),
                           fetch=lambda url, robots: PAGE)
        self.assertEqual(report["eligible"],0)
        self.assertEqual(report["evaluated"],0)

    def test_network_failure_is_held_not_published(self):
        row={"candidate":candidate(),"observations":9}
        def failure(url,robots):
            raise OSError("Temporary unavailable")
        report=p.inspect({"items":{"x":row}},catalogue(),dt.date(2026,11,1),
                         fetch=failure)
        self.assertEqual(report["verifiedPreviewOnly"],0)
        self.assertEqual(report["held"],1)
        self.assertFalse(report["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
