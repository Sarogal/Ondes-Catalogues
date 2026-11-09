"""Adversarial, offline validation of private-only evidence diagnostics."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_private_qualification_diagnostics import summarise, reason_bucket

TODAY = date(2026, 11, 9)


def raw_report():
    return {
        "date": "2026-11-09", "mode": "preview_no_public_write",
        "review_slot": 2, "backlog_total": 229,
        "eligible_with_reviewed_venue": 32,
        "review_batch": 3, "review_batches": 3,
        "checked": 2, "accepted_preflight": 0,
        "deferred_or_duplicates": 2,
        "details": [
            {
                "status": "unverified",
                "reason": "page OpenAgenda dynamique : horaires illisibles sans JavaScript",
                "source_url": "https://openagenda.com/a/events/secret-id",
                "date": "2026-12-05",
                "title": "Événement privé SECRET",
                "private_token": "TOPSECRET"
            },
            {
                "status": "deferred",
                "reason": "Position source incompatible avec le registre vérifié",
                "source_url": "https://openagenda.com/b/events/secret-id",
                "date": "2026-11-20"
            }
        ],
        "reason_counts": {"SECRET-TOKEN": 7}
    }


class PrivateQualificationDiagnosticsTests(unittest.TestCase):
    def test_offline_summary_is_private_counts_only(self):
        src = raw_report()
        result = summarise(src, TODAY, 2)
        self.assertEqual(result["reason_groups"], {
            "official_page_dynamic": 1, "venue_or_gps": 1
        })
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["publications"], 0)
        self.assertEqual(result["mode"], "private_diagnostic_only")
        out = json.dumps(result)
        for forbidden in (
            "openagenda.com", "secret-id", "TOPSECRET", "Événement privé",
            "SECRET-TOKEN", "2026-12-05"
        ):
            self.assertNotIn(forbidden, out)

    def test_rejects_inconsistent_counts_and_identity(self):
        source = raw_report()
        changes = (
            ("date", "2026-11-08"),
            ("review_slot", 1),
            ("mode", "publish"),
            ("checked", 16),
            ("checked", -1),
            ("checked", True),
            ("backlog_total", 9000),
            ("eligible_with_reviewed_venue", 999),
            ("accepted_preflight", 2),
            ("deferred_or_duplicates", 1),
            ("review_batch", 4),
            ("review_batches", 0),
            ("review_batches", 4001)
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                changed = dict(source, **{key: value})
                with self.assertRaises(ValueError):
                    summarise(changed, TODAY, 2)
        with self.assertRaises(ValueError):
            summarise(source, TODAY, 1)

    def test_untrusted_status_or_missing_details_blocks(self):
        source = raw_report()
        for bad in (
            dict(source, details=[]),
            dict(source, details=[*source["details"], {}]),
            dict(source, details=[dict(source["details"][0],
                                       status="approved"), source["details"][1]]),
            dict(source, details=None)
        ):
            with self.assertRaises(ValueError):
                summarise(bad, TODAY, 2)

    def test_clean_empty_batch_and_one_approved(self):
        source = raw_report()
        empty = dict(
            source, eligible_with_reviewed_venue=0,
            review_batch=0, review_batches=0, checked=0,
            accepted_preflight=0, deferred_or_duplicates=0, details=[])
        result = summarise(empty, TODAY, 2)
        self.assertEqual(result["reason_groups"], {})
        yes = dict(source, checked=1, accepted_preflight=1,
                   deferred_or_duplicates=0, details=[])
        result = summarise(yes, TODAY, 2)
        self.assertEqual((result["checked"], result["accepted_preflight"]), (1, 1))

    def test_reason_classification_never_exposes_untrusted_text(self):
        payload = {
            "status": "unverified",
            "reason": "Erreur réseau token secret123 https://evil.invalid"
        }
        self.assertEqual(reason_bucket(payload), "transport_or_data")
        self.assertEqual(reason_bucket({"status": "unknown", "reason": "secret"}), "other")
        self.assertEqual(reason_bucket({"status": "already_published",
                                        "reason": "secret"}), "already_published")


if __name__ == "__main__":
    unittest.main()
