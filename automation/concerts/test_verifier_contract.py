"""Pure offline regression for a single reviewed source-wide verifier manifest.

No URLs are fetched. No private data, approval files or public catalogues
are written. Integration and publisher signatures retain their own tests.
"""
from __future__ import annotations

import datetime as dt
import importlib
import sys
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import official_recheck
import registry_funnel
import verifier_contract as contract


TODAY = dt.date(2026, 11, 18)


def candidate(source, number):
    return {
        "source": source,
        "candidateId": "synthetic-" + str(number),
        "name": "SYNTHETIC ACT + SECOND ACT",
        "date": "2027-02-10",
        "sourceUrl": "https://unit-test.invalid/events/" + str(number),
        "reviewBucket": "genre_tag_review",
        "officialDetailFound": True,
        "city": "Example",
        "venue": "Example Hall",
        "publicationAllowed": False,
        "reviewRequired": True,
    }


def registry(sources):
    return {
        "schema": registry_funnel.REGISTRY_SCHEMA,
        "items": {
            str(n): {
                "candidate": candidate(source, n),
                "status": "pending_review",
                "stableObservations": 2,
                "identitySignature": "synthetic-stable",
            }
            for n, source in enumerate(sources)
        },
    }


class VerifiedSourceContractTests(unittest.TestCase):
    def test_manifest_is_immutable_and_cannot_be_extended_by_registry(self):
        self.assertIsInstance(contract.VERIFIER_SPECS, MappingProxyType)
        with self.assertRaises(TypeError):
            contract.VERIFIER_SPECS["untrusted_source"] = None
        self.assertNotIn("untrusted_source", contract.VERIFIER_SPECS)

    def test_diagnostic_sets_are_exactly_derived_from_approved_dispatch(self):
        self.assertEqual(
            contract.AUTOMATIC_RECHECK_SOURCES,
            frozenset(contract.VERIFIER_SPECS),
        )
        self.assertEqual(
            registry_funnel.AUTOMATIC_RECHECK_SOURCES,
            contract.AUTOMATIC_RECHECK_SOURCES,
        )
        self.assertEqual(
            registry_funnel.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES,
            contract.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES,
        )
        self.assertTrue(contract.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES
                        <= contract.AUTOMATIC_RECHECK_SOURCES)
        self.assertNotIn("agenda_officiel_rex_genre",
                         contract.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES)
        self.assertIn("bbc_official_detail_review",
                      contract.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES)
        self.assertIn("agenda_officiel_bonjour_minuit_detail_review",
                      contract.DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES)

    def test_every_declared_verifier_has_a_real_callable(self):
        self.assertEqual(
            {source for source, spec in contract.VERIFIER_SPECS.items()
             if spec.module is None},
            {"agenda_officiel_rex_genre", "agenda_officiel_atabal_detail"},
        )
        for source, spec in contract.VERIFIER_SPECS.items():
            with self.subTest(source=source):
                if spec.module:
                    verifier = importlib.import_module(spec.module)
                    self.assertTrue(callable(getattr(verifier, "verify", None)))

    def test_unknown_source_is_never_dispatched_even_with_a_valid_url(self):
        for source in ("unregistered", "agenda_officiel_evil_detail", ["bbc_official_detail_review"]):
            with self.subTest(source=str(source)):
                with patch.object(official_recheck.importlib, "import_module") as importer:
                    with self.assertRaises(ValueError):
                        official_recheck.verify(
                            {"source": source, "sourceUrl": "https://bbc.example/"},
                            "<main>fake HTML</main>", {}, TODAY)
                    importer.assert_not_called()

    def test_every_source_wide_module_dispatch_uses_trusted_name(self):
        class FakeModule:
            def verify(self, raw, html, catalogue, today):
                return {"verifiedBy": raw["source"], "day": today.isoformat()}
        for source, spec in contract.VERIFIER_SPECS.items():
            if spec.module is None:
                continue
            with self.subTest(source=source):
                with patch.object(official_recheck.importlib, "import_module",
                                  return_value=FakeModule()) as imported:
                    result = official_recheck.verify(
                        candidate(source, 3), "<main>synthetic</main>",
                        {}, TODAY)
                    imported.assert_called_once_with(spec.module)
                    self.assertEqual(result["verifiedBy"], source)

    def test_process_eligibility_uses_the_same_source_registry(self):
        sources = sorted(contract.VERIFIER_SPECS)
        # Only this selection test uses a fake verifier; full source proof,
        # signed approvals and the real publisher have independent tests.
        def simulated_verify(raw, html, catalogue, today):
            return {
                "reviewDecision": "approved",
                "event": {
                    "id": raw["candidateId"], "officialUrl": raw["sourceUrl"],
                    "date": raw["date"], "artistIds": [],
                },
                "newArtists": [],
            }

        ledger = {"schema": "grossesondes.concert.approvals.v1",
                  "approvals": []}
        public = {"schemaVersion": 1, "mode": "preview-public-unlisted",
                  "artists": [], "events": []}
        rows = registry(sources + ["agenda_officiel_unregistered"])
        with patch.object(official_recheck, "verify",
                          side_effect=simulated_verify):
            _, report = official_recheck.process(
                rows, public, ledger, TODAY,
                fetch=lambda url, cache: "<main>synthetic</main>",
                limit=30)
        # The generic structured source is registered, but unlike fixed
        # legacy verifiers it still requires an independently pinned venue
        # and an exact first-party HTTPS host BEFORE any network call.
        permitted = len(sources) - 1
        self.assertEqual(report["evaluated"], len(sources))
        self.assertEqual(len(report["newApprovals"]), permitted)
        self.assertTrue(any(
            row["candidateId"] == "synthetic-" + str(sources.index(
                "agenda_officiel_structuré"))
            for row in report["held"]))
        self.assertNotIn("synthetic-" + str(len(sources)), report["newApprovals"])

    def test_private_funnel_and_rechecker_classify_same_eligible_sources(self):
        sources = sorted(contract.VERIFIER_SPECS)
        rows = registry(sources + ["agenda_officiel_unregistered"])
        report = registry_funnel.build(
            rows,
            {"schema": registry_funnel.APPROVALS_SCHEMA, "approvals": []},
            {"schemaVersion": 1, "events": []},
            TODAY,
        )
        self.assertEqual(report["readyForIndependentRecheck"], len(sources))
        self.assertEqual(
            report["exclusiveBlockingReasons"]["verified_adapter_not_available"],
            1,
        )
        self.assertFalse(report["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
