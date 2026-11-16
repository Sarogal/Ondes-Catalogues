"""Offline adversarial tests for an UNPUBLISHABLE municipal sync rehearsal."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_municipal_sync_rehearsal import (
    SCHEMA, simulate_municipal_sync,
)
from ptitesondes_municipal_appendonly_dryrun import canonical_sha256
from test_ptitesondes_municipal_batch_readiness import (
    historical, sample_nine,
)
from test_ptitesondes_nonmusic_release_contract import TODAY


def stamps(dossiers, when=None):
    d = when if when is not None else TODAY.isoformat()
    return {
        doc["review"]["candidates"][0]["review_id"]: {
            "source_checked_on": d, "geo_checked_on": d,
        }
        for doc in dossiers
    }


def run(*, reference=None, current=None, dossiers=None, stamp_map=None,
        token="test-only-token", gh=None, source=None, geo=True,
        ref_pin=None, cur_pin=None):
    ref = reference if reference is not None else historical()
    live = current if current is not None else historical()
    original, get_source, get_github = sample_nine(public=live)
    selected = dossiers if dossiers is not None else original
    return simulate_municipal_sync(
        ref, live, selected, TODAY,
        reference_sha256=ref_pin or canonical_sha256(ref),
        current_sha256=cur_pin or canonical_sha256(live),
        planning_stamps=stamp_map if stamp_map is not None
        else stamps(selected),
        token=token, source_get=source or get_source,
        github_get=gh or get_github,
        geo_check=lambda e: (geo, "synthetic location only"),
    )


class IsolatedSyncRehearsalTests(unittest.TestCase):
    def test_nine_hypothetical_append_without_publication_or_output_events(self):
        ref, live = historical(), historical()
        ref_copy, live_copy = deepcopy(ref), deepcopy(live)
        # Even an injected malicious existing merger is never executed.
        with patch("merge_policy.merge", side_effect=AssertionError(
            "production publisher must not be called"
        )):
            out = run(reference=ref, current=live)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["reference_events_preserved"], 548)
        self.assertEqual(out["current_events_preserved"], 548)
        self.assertEqual(out["hypothetical_in_memory_additions"], 9)
        self.assertEqual(out["hypothetical_in_memory_total"], 557)
        self.assertTrue(out["historical_prefix_unchanged"])
        self.assertTrue(out["planning_stamps_are_not_signed_proof"])
        self.assertTrue(out["requires_independent_source_and_gps_attestation"])
        self.assertTrue(out["production_category_policy_unchanged"])
        self.assertTrue(out["municipal_publisher_not_connected"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertEqual(out["public_writes"], 0)
        for forbidden in ("events", "additions", "updates", "patch",
                          "safe_to_publish", "catalogue"):
            self.assertNotIn(forbidden, out)
        self.assertEqual(ref, ref_copy)
        self.assertEqual(live, live_copy)

    def test_unapproved_batch_is_all_or_nothing(self):
        out = run(token=None)
        self.assertFalse(out["batch_readiness_confirmed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertEqual(out["hypothetical_in_memory_total"], 548)
        self.assertIn("batch_evidence_or_approval_incomplete",
                      out["simulation_blockers"])
        self.assertEqual(out["public_writes"], 0)

    def test_realistic_unknown_access_remains_unapproved_without_comments(self):
        current = historical()
        docs, get_source, get_github = sample_nine(
            public=current, known_conditions=False
        )
        def no_owner_comments(url, token):
            if "/comments?" in url:
                return []
            return get_github(url, token)
        out = run(current=current, dossiers=docs, source=get_source,
                  gh=no_owner_comments)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertFalse(out["publication_ready"])

    def test_invalid_planning_stamps_never_allow_pseudo_append(self):
        docs, source, private = sample_nine()
        good = stamps(docs)
        first = docs[0]["review"]["candidates"][0]["review_id"]
        variants = [
            {}, {first: good[first]},
            dict(good, unrelated={"source_checked_on": TODAY.isoformat(),
                                  "geo_checked_on": TODAY.isoformat()}),
            dict(good, **{first: {"source_checked_on": "2026-11-01",
                                 "geo_checked_on": TODAY.isoformat()}}),
            dict(good, **{first: {"source_checked_on": "2026-11-17",
                                 "geo_checked_on": TODAY.isoformat()}}),
            dict(good, **{first: {"source_checked_on": TODAY.isoformat(),
                                 "geo_checked_on": "nonsense"}}),
            dict(good, **{first: {"source_checked_on": TODAY.isoformat()}}),
        ]
        for i, variant in enumerate(variants):
            with self.subTest(case=i):
                out = run(dossiers=docs, source=source, gh=private,
                          stamp_map=variant)
                self.assertEqual(out["hypothetical_in_memory_additions"], 0)
                self.assertFalse(out["publication_ready"])

    def test_duplicate_batch_entry_never_allows_partial_insert(self):
        docs, source, private = sample_nine()
        docs[2] = deepcopy(docs[1])
        out = run(dossiers=docs, source=source, gh=private)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertEqual(out["public_writes"], 0)

    def test_bad_gps_or_changed_official_page_fail_closed(self):
        self.assertEqual(run(geo=False)["hypothetical_in_memory_additions"], 0)
        docs, get_source, get_private = sample_nine()
        def changed(url):
            html = get_source(url)
            if "/evenement/simulation-" in url:
                return html.replace("Gratuit.", "Tarif différent.")
            return html
        out = run(dossiers=docs, source=changed, gh=get_private)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_publication_in_other_feed_invalidates_old_approval(self):
        ref = historical()
        current = deepcopy(ref)
        current["events"].append({
            "id": "already-published-elsewhere",
            "title": "unrelated",
            "date_start": "2026-11-20",
            "date_end": "2026-11-20",
            "city": "Paris", "venue": "Venue",
            "source_url": "https://publisher.example/one",
        })
        docs, get_source, get_private = sample_nine(public=ref)
        out = run(reference=ref, current=current, dossiers=docs,
                  source=get_source, gh=get_private)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertIn("batch_evidence_or_approval_incomplete",
                      out["simulation_blockers"])

    def test_historical_reordering_or_mutation_is_hard_error(self):
        ref, current = historical(), historical()
        current["events"][0], current["events"][1] = (
            current["events"][1], current["events"][0]
        )
        with self.assertRaisesRegex(ValueError, "historical_catalogue_modified"):
            run(reference=ref, current=current)
        current = historical()
        current["events"][0]["title"] = "modified"
        with self.assertRaisesRegex(ValueError, "historical_catalogue_modified"):
            run(reference=ref, current=current)

    def test_stale_sha_pin_never_approves(self):
        with self.assertRaisesRegex(ValueError, "catalogue_changed"):
            run(cur_pin="f" * 64)
        with self.assertRaisesRegex(ValueError, "catalogue_changed"):
            run(ref_pin="f" * 64)

    def test_no_write_even_after_unexpected_mutation(self):
        ref = historical()
        current = historical()
        docs, get_source, get_private = sample_nine(public=current)
        first_title = current["events"][0]["title"]
        def malicious_geo(ev):
            current["events"][0]["title"] = "tampered"
            return True, "untrusted"
        with self.assertRaisesRegex(ValueError, "historical_catalogue_mutated"):
            simulate_municipal_sync(
                ref, current, docs, TODAY,
                reference_sha256=canonical_sha256(ref),
                current_sha256=canonical_sha256(current),
                planning_stamps=stamps(docs), token="test-only-token",
                source_get=get_source, github_get=get_private,
                geo_check=malicious_geo,
            )
        self.assertNotEqual(current["events"][0]["title"], first_title)

    def test_no_private_network_or_file_write_is_exposed(self):
        out = run()
        self.assertNotIn("path", out)
        self.assertNotIn("token", out)
        self.assertNotIn("source_url", out)
        self.assertIs(out["publication_ready"], False)


if __name__ == "__main__":
    unittest.main()
