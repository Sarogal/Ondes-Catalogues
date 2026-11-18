"""Adversarial tests for read-only redacted funnel reporting."""
import json
import unittest
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_autonomy_funnel import summarize


class AutonomyFunnelTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 18)
        self.collection = {
            "day": "2026-11-18", "sources_interrogees": 48,
            "openagenda_agendas_configures": 16,
            "openagenda_agendas_interroges": 16,
            "sources_en_echec": [], "seances_pertinentes": 476,
            "decouvertes_nouvelles_en_attente": 0,
            "en_attente_total": 5,
        }
        self.qual = {
            "day": "2026-11-18", "backlog_total": 5,
            "checked": 2, "accepted_preflight": 1,
            "admission_diagnostics": {
                "raw_leads": 5,
                "reason_counts": {"eligible": 2, "venue_gps_unverified": 2,
                                  "collector": 1},
                "top_unverified_venues": [{
                    "city": "PRIVATE_CITY_SHOULD_NOT_LEAK",
                    "venue": "PRIVATE_VENUE_SHOULD_NOT_LEAK",
                }],
            },
        }
        self.catalogue = {
            "version": 3, "updated_at": "2026-11-17T08:49:57+01:00",
            "events": [
                {"id": "future", "category": "conte-musical",
                 "date_start": "2026-12-15", "date_end": "2026-12-15"},
                {"id": "past", "category": "concert",
                 "date_start": "2026-11-01", "date_end": "2026-11-01"},
            ],
        }

    def test_counts_are_reconciled_and_calls_not_mislabeled_sources(self):
        result = summarize(self.collection, self.qual, self.catalogue, self.day)
        self.assertEqual(result["collection"]["api_requests_successful_not_distinct_sources"], 48)
        self.assertIsNone(result["collection"]["distinct_source_organizations"])
        self.assertEqual(result["backlog"]["first_gate_reason_counts"]["venue_gps_unverified"], 2)
        self.assertEqual(result["public"]["future_events"], 1)
        self.assertEqual(result["public"]["future_categories"], {"conte-musical": 1})
        self.assertIsNone(result["backlog"]["automatically_recoverable_count"])
        self.assertEqual(result["safety"]["public_writes"], 0)

    def test_private_names_and_urls_never_appear(self):
        self.collection["sources_en_echec"] = ["https://PRIVATE_SOURCE_SHOULD_NOT_LEAK"]
        self.qual["private_untrusted"] = "PRIVATE_LEAD_URL_SHOULD_NOT_LEAK"
        output = json.dumps(summarize(self.collection, self.qual, self.catalogue, self.day))
        for token in ("PRIVATE_CITY_SHOULD_NOT_LEAK",
                      "PRIVATE_VENUE_SHOULD_NOT_LEAK",
                      "PRIVATE_SOURCE_SHOULD_NOT_LEAK",
                      "PRIVATE_LEAD_URL_SHOULD_NOT_LEAK"):
            self.assertNotIn(token, output)
        self.assertEqual(json.loads(output)["collection"]["failed_source_requests_or_agendas"], 1)

    def test_inconsistent_backlog_fails_closed(self):
        self.qual["admission_diagnostics"]["reason_counts"]["eligible"] = 3
        with self.assertRaisesRegex(ValueError, "backlog_reasons_do_not_reconcile"):
            summarize(self.collection, self.qual, self.catalogue, self.day)

    def test_differing_days_and_stale_report_fail_closed(self):
        self.collection["day"] = "2026-11-17"
        with self.assertRaisesRegex(ValueError, "collection_day_mismatch"):
            summarize(self.collection, self.qual, self.catalogue, self.day)

    def test_colliding_public_ids_fail_closed(self):
        self.catalogue["events"].append(dict(self.catalogue["events"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_public_id"):
            summarize(self.collection, self.qual, self.catalogue, self.day)

    def test_unknown_reason_text_cannot_leak(self):
        self.qual["admission_diagnostics"]["reason_counts"] = {
            "eligible": 4, "https://private.invalid/secret": 1
        }
        with self.assertRaisesRegex(ValueError, "invalid_reason_code"):
            summarize(self.collection, self.qual, self.catalogue, self.day)


if __name__ == "__main__":
    unittest.main()
