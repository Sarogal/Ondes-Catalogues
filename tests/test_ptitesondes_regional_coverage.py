"""Public catalogue regional coverage: read-only, exact and fail-closed."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_regional_coverage import REGIONS, regional_coverage

TODAY = date(2026, 11, 14)


def event(event_id, start="2026-11-14", end="2026-11-14",
          region=None, city="Montpellier"):
    return {
        "id": event_id, "date_start": start, "date_end": end,
        "region": region, "city": city,
        "source_url": "https://some-public-source.invalid/never-show",
    }


class RegionalCoverageTests(unittest.TestCase):
    def test_real_region_alias_is_counted_only_once_and_no_catalogue_edit(self):
        entries = [
            event("paca-ascii", region="Provence-Alpes-Côte d'Azur"),
            event("paca-curly", region="Provence-Alpes-Côte d’Azur"),
            event("corsica", region="Corse", end="2027-02-01"),
            event("unknown-city", region=None, city="Montpellier"),
            event("alien", region="Atlantide"),
            event("past", start="2026-10-01", end="2026-10-31",
                  region="Bretagne"),
            event("bad-date", start="2026-02-31", end="2026-11-18",
                  region="Occitanie"),
        ]
        before = deepcopy(entries)
        output = regional_coverage(entries, TODAY)
        self.assertEqual(entries, before)
        self.assertEqual(output["future_events"], 5)
        self.assertEqual(output["attributed_region"], 3)
        self.assertEqual(output["missing_region"], 1)
        self.assertEqual(output["unrecognized_region"], 1)
        self.assertEqual(output["invalid_or_missing_dates"], 1)
        self.assertEqual(output["alias_spellings_collapsed"], 1)
        self.assertEqual(output["regions_with_zero_events"], 16)
        self.assertEqual(len(output["regions"]), len(REGIONS))
        counts = {item["region"]: item["future_events"]
                  for item in output["regions"]}
        self.assertEqual(counts["Provence-Alpes-Côte d’Azur"], 2)
        self.assertEqual(counts["Corse"], 1)
        self.assertEqual(counts["Bretagne"], 0)
        self.assertNotIn("Provence-Alpes-Côte d'Azur", counts)
        self.assertNotIn("source_url", str(output))
        self.assertNotIn("Montpellier", str(output))
        self.assertNotIn("Atlantide", str(output))

    def test_today_counts_and_past_is_excluded(self):
        value = regional_coverage([
            event("today", start="2026-11-01", end="2026-11-14",
                  region="Normandie"),
            event("yesterday", start="2026-11-01", end="2026-11-13",
                  region="Normandie"),
            event("tomorrow", start="2026-11-15", end="2026-11-15",
                  region="Mayotte"),
        ], TODAY)
        self.assertEqual(value["future_events"], 2)
        self.assertEqual(value["attributed_region"], 2)
        self.assertEqual(
            next(x["future_events"] for x in value["regions"]
                 if x["region"] == "Normandie"), 1)

    def test_missing_date_is_anomaly_not_a_future_published_claim(self):
        value = regional_coverage([
            {"id": "without-date", "region": "Occitanie"},
            event("reversed", start="2026-11-20", end="2026-11-15",
                  region="Occitanie"),
            event("invalid-lexical", start="2026-11-1", end="2026-12-01",
                  region="Occitanie"),
        ], TODAY)
        self.assertEqual(value["future_events"], 0)
        self.assertEqual(value["invalid_or_missing_dates"], 3)

    def test_fail_closed_on_wrong_input_types(self):
        for value in (None, {}, "events", [None], [1]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    regional_coverage(value, TODAY)


if __name__ == "__main__":
    unittest.main()
