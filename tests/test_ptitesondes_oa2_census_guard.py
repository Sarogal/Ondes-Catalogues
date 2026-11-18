"""Public-safe tests for the private redacted OpenAgenda inventory report."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ptitesondes_oa2_census_guard as guard


def sample():
    return {
        "schema": guard.SCHEMA, "mode": guard.MODE, "configured_agendas": 16,
        "counts": {"api_identity_concordant": 9, "api_identity_mismatch": 2,
                   "api_unavailable_or_unverified": 5,
                   "api_official_indicator_only": 5,
                   "api_self_declared_external_reference": 4},
        "independently_confirmed_owners": 0,
        "organizer_sessions_attested": 0,
        "licences_reviewed": 0,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0,
        "contains_identifiers_or_private_candidate_data": False,
    }


class CensusGuardTests(unittest.TestCase):
    def test_accepts_complete_redacted_census(self):
        self.assertEqual(guard.guarded(sample()), sample())

    def test_no_identifying_fields_even_when_numeric_counters_pass(self):
        for field, value in (
            ("url", "https://openagenda.com/example"), ("uid", 1234),
            ("key", "oa_pk_secret"), ("title", "Sensitive event"),
            ("source_records", [{"uid": 1234}]), ("checked_at", "2026-11-18"),
        ):
            row = sample()
            row[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                guard.guarded(row)

    def test_rejects_smuggling_and_invented_counts(self):
        mutations = [
            ("configured_agendas", True), ("configured_agendas", 0),
            ("configured_agendas", 101), ("counts", {"url": 1}),
            ("counts", {"api_identity_concordant": 16.5}),
            ("counts", {"api_identity_concordant": -1}),
            ("counts", []),
            ("publisher_connected", True), ("approval_granted", 1),
            ("public_writes", True), ("public_writes", 1),
            ("licences_reviewed", 1),
            ("independently_confirmed_owners", 2),
            ("contains_identifiers_or_private_candidate_data", True),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=str(value)):
                row = sample()
                row[field] = value
                with self.assertRaises(ValueError):
                    guard.guarded(row)

    def test_rejects_doubled_or_incomplete_identity_inventory(self):
        row = sample()
        row["counts"]["api_identity_concordant"] = 15
        with self.assertRaises(ValueError):
            guard.guarded(row)
        row["counts"]["api_identity_concordant"] = 1
        with self.assertRaises(ValueError):
            guard.guarded(row)
        row = sample()
        row["counts"]["api_private_or_restricted"] = 10
        with self.assertRaises(ValueError):
            guard.guarded(row)

    def test_workflow_keeps_api_key_in_trusted_environment_only(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn("OPENAGENDA_READ_KEY: ${{ secrets.OPENAGENDA_READ_KEY }}", workflow)
        self.assertIn("public/scripts/ptitesondes_openagenda_v2_agenda_census.py", workflow)
        self.assertIn("public/scripts/ptitesondes_oa2_census_guard.py", workflow)
        self.assertIn("src/automation/sources.json", workflow)
        self.assertIn("RUN_MODE", workflow)
        self.assertIn("state/automation-intake/ptitesondes", workflow)
        self.assertIn("reports/openagenda-v2-agendas-$DAY.json", workflow)


if __name__ == "__main__":
    unittest.main()
