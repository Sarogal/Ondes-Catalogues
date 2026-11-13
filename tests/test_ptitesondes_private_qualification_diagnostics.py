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
        "eligible_with_reviewed_venue": 32, "eligible_raw": 40,
        "duplicate_collector_leads_skipped": 7,
        "conflicting_uid_days_deferred": 1,
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
        self.assertEqual(result["eligible_raw"], 40)
        self.assertEqual(result["not_eligible_for_review"], 189)
        self.assertEqual(result["duplicate_collector_leads_skipped"], 7)
        self.assertEqual(result["conflicting_uid_days_deferred"], 1)
        self.assertEqual(result["publications"], 0)
        self.assertEqual(result["mode"], "private_diagnostic_only")
        out = json.dumps(result)
        for forbidden in (
            "openagenda.com", "secret-id", "TOPSECRET", "Événement privé",
            "SECRET-TOKEN", "2026-12-05"
        ):
            self.assertNotIn(forbidden, out)

    def test_prebatch_published_skips_are_counted_without_ids_or_proofs(self):
        src = dict(raw_report(), eligible_with_reviewed_venue=27,
                   already_published_before_batch=5)
        summary = summarise(src, TODAY, 2)
        self.assertEqual(summary["already_published_before_batch"], 5)
        self.assertEqual(summary["eligible"], 27)
        self.assertEqual(summary["checked"], 2)
        safe = json.dumps(summary)
        self.assertNotIn("secret-id", safe)
        self.assertNotIn("TOPSECRET", safe)
        for count in (-1, True, 230, 6, "5"):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    summarise(dict(src, already_published_before_batch=count),
                              TODAY, 2)

    def test_private_admission_venues_survive_only_in_private_summary(self):
        report = raw_report()
        report["admission_diagnostics"] = {
            "scope": "private_raw_backlog_only_no_publication",
            "raw_leads": 229,
            "reason_counts": {"eligible": 40, "venue_gps_unverified": 185,
                              "session_date": 4},
            "top_unverified_venues": [
                {"city": "Tourcoing", "venue": "Médiathèque André Malraux",
                 "lead_occurrences": 29},
                {"city": "Nantes", "venue": "Centre socioculturel des Bourderies - ACCOORD",
                 "lead_occurrences": 26},
            ]
        }
        result = summarise(report, TODAY, 2)
        private = result["admission_diagnostics"]
        self.assertEqual(private["raw_leads"], 229)
        self.assertEqual(private["reason_counts"]["venue_gps_unverified"], 185)
        self.assertEqual(private["top_unverified_venues"][0]["lead_occurrences"], 29)
        self.assertEqual(result["publications"], 0)
        self.assertNotIn("source_url", json.dumps(result))

    def test_admission_diagnostics_cannot_claim_more_than_private_backlog(self):
        src = raw_report()
        valid = {"scope": "private_raw_backlog_only_no_publication",
                 "raw_leads": 229,
                 "reason_counts": {"eligible": 40, "venue_gps_unverified": 189},
                 "top_unverified_venues": [
                     {"city": "Tourcoing", "venue": "Médiathèque André Malraux",
                      "lead_occurrences": 29}]}
        bad = (
            dict(valid, raw_leads=230),
            dict(valid, reason_counts={"eligible": 41, "venue_gps_unverified": 188}),
            dict(valid, reason_counts={"eligible": 40, "venue_gps_unverified": 188}),
            dict(valid, top_unverified_venues=[
                {"city": "Tourcoing", "venue": "Médiathèque André Malraux",
                 "lead_occurrences": 190}]),
            dict(valid, top_unverified_venues=[
                {"city": "Tourcoing", "venue": "Médiathèque André Malraux",
                 "lead_occurrences": 20},
                {"city": "Tourcoing", "venue": "Médiathèque André Malraux",
                 "lead_occurrences": 20}]),
            dict(valid, top_unverified_venues=[
                {"city": "Ville", "venue": "https://private.example/secret",
                 "lead_occurrences": 1}]),
            dict(valid, top_unverified_venues=[
                {"city": "Ville", "venue": "A" * 181,
                 "lead_occurrences": 1}]),
            dict(valid, reason_counts={"eligible": 40, "unknown": 189}),
            dict(valid, raw_leads=True),
        )
        for case in bad:
            with self.subTest(case=str(case)[:80]):
                with self.assertRaises(ValueError):
                    summarise(dict(src, admission_diagnostics=case), TODAY, 2)

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
            ("eligible_raw", 250),
            ("eligible_raw", 31),
            ("eligible_raw", True),
            ("duplicate_collector_leads_skipped", 40),
            ("conflicting_uid_days_deferred", -1),
            ("conflicting_uid_days_deferred", 100),
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
            source, eligible_with_reviewed_venue=0, eligible_raw=0,
            duplicate_collector_leads_skipped=0,
            conflicting_uid_days_deferred=0,
            review_batch=0, review_batches=0, checked=0,
            accepted_preflight=0, deferred_or_duplicates=0, details=[])
        result = summarise(empty, TODAY, 2)
        self.assertEqual(result["reason_groups"], {})
        yes = dict(source, checked=1, accepted_preflight=1,
                   deferred_or_duplicates=0, details=[])
        result = summarise(yes, TODAY, 2)
        self.assertEqual((result["checked"], result["accepted_preflight"]), (1, 1))

    def test_official_page_visible_but_missing_proof_is_not_network_outage(self):
        self.assertEqual(reason_bucket({
            "status": "unverified",
            "reason": "date complète non confirmée sur la fiche officielle"
        }), "date_or_time")
        self.assertEqual(reason_bucket({
            "status": "unverified",
            "reason": "tous les horaires ne sont pas confirmés sur la fiche officielle"
        }), "date_or_time")
        self.assertEqual(reason_bucket({
            "status": "unverified",
            "reason": "lieu absent de la fiche officielle"
        }), "venue_or_gps")
        self.assertEqual(reason_bucket({
            "status": "unverified",
            "reason": "titre non confirmé en en-tête de la fiche officielle"
        }), "title_or_identity")
        self.assertEqual(reason_bucket({
            "status": "deferred",
            "reason": "URL canonique différente"
        }), "uid_or_source")
        self.assertEqual(reason_bucket({
            "status": "unverified",
            "reason": "page officielle inaccessible"
        }), "official_page_unavailable")

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
