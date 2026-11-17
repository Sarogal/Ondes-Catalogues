"""Adversarial no-network tests; ALL Gosier examples are synthetic fixtures."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_municipal_attested_batch_rehearsal import (
    SCHEMA, inspect_attested_municipal_sync,
)
from ptitesondes_municipal_appendonly_dryrun import canonical_sha256
from ptitesondes_municipal_source_geo_attestation import (
    RECEIPT_SCHEMA, attestation_comment_line,
)
from ptitesondes_municipal_human_decision import (
    API, APPROVER, canonical_digest, html_digest, request_digest,
)
from test_ptitesondes_municipal_batch_readiness import historical, sample_nine
from test_ptitesondes_municipal_source_geo_attestation import (
    NOW, STAMP, SYNTHETIC_VENUE,
)
from test_ptitesondes_nonmusic_release_contract import TODAY


def scenario(*, current=None, known_conditions=True):
    reference = historical()
    current = historical() if current is None else current
    dossiers, source, private = sample_nine(
        public=current, known_conditions=known_conditions,
    )
    bundles, comments = [], []
    for idx, dossier in enumerate(dossiers):
        c = dossier["review"]["candidates"][0]
        access = dossier["access"]["reviewed"][0]
        manifest = dossier["manifest"]
        record = deepcopy(SYNTHETIC_VENUE)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "mode": "request_private_source_geo_attestation",
            "review_id": c["review_id"],
            "pr_number": manifest["pr_number"],
            "head_sha": manifest["head_sha"],
            "manifest_sha256": request_digest(manifest),
            "candidate_sha256": canonical_digest(c),
            "access_sha256": canonical_digest(access),
            "catalogue_sha256": canonical_digest(current),
            "event_html_sha256": html_digest(source(c["official_event_url"])),
            "calendar_html_sha256": html_digest(source(c["calendar_url"])),
            "calendar_url": c["calendar_url"],
            "venue_registry_sha256": canonical_digest(record),
            "venue_official_url": record["official"],
            "venue_geo_url": record["geo_source"],
        }
        bundles.append({**deepcopy(dossier), "receipt": receipt})
        comments.append({
            "id": 20001 + idx,
            "body": attestation_comment_line(receipt, "ATTEST"),
            "user": {"login": APPROVER, "type": "User"},
            "author_association": "OWNER",
            "created_at": STAMP,
        })

    def github(url, token):
        if url == API + "/issues/88/comments?per_page=100&page=1":
            return private(url, token) + deepcopy(comments)
        return private(url, token)

    return reference, current, bundles, source, github, comments


def run(*, variant=None, get=None, gh=None, records=None, token="test-only-token",
        ref_pin=None, cur_pin=None, now=NOW, current=None,
        known_conditions=True):
    reference, live, bundles, source, private, comments = scenario(
        current=current, known_conditions=known_conditions,
    )
    if variant:
        variant(reference, live, bundles, comments)
    return inspect_attested_municipal_sync(
        reference, live, bundles, TODAY,
        reference_sha256=ref_pin or canonical_sha256(reference),
        current_sha256=cur_pin or canonical_sha256(live),
        token=token, source_get=get or source, github_get=gh or private,
        geo_check=lambda e: (True, "synthetic geo, NOT real evidence"),
        registry=deepcopy(SYNTHETIC_VENUE) and (
            [deepcopy(SYNTHETIC_VENUE)] if records is None else records
        ),
        now=now,
    )


class AttestedBatchRehearsalTests(unittest.TestCase):
    def test_all_nine_private_attestations_enable_only_memory_model(self):
        snapshot = historical()
        with patch("merge_policy.merge", side_effect=AssertionError(
            "production merge forbidden"
        )):
            out = run()
        self.assertEqual(out["schema"], SCHEMA)
        self.assertTrue(out["municipal_batch_passed"])
        self.assertTrue(out["all_private_source_geo_attestations_passed"])
        self.assertTrue(out["in_memory_rehearsal_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 9)
        self.assertEqual(out["reference_events_preserved"], 548)
        self.assertEqual(out["current_events_preserved"], 548)
        self.assertEqual(historical(), snapshot)
        self.assertEqual(out["simulation_blockers"], [])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertEqual(out["public_writes"], 0)
        self.assertTrue(out["planning_dates_are_not_evidence"])
        self.assertTrue(out["gps_provider_not_refetched"])
        self.assertTrue(out["owner_comment_sha256_is_not_a_digital_signature"])
        for forbidden in ("events", "additions", "patch", "patch.v1",
                          "catalogue", "token", "review_id"):
            self.assertNotIn(forbidden, out)

    def test_one_missing_receipt_blocks_whole_lot(self):
        def bad(_, __, bundles, ___):
            bundles[4]["receipt"] = None
        out = run(variant=bad)
        self.assertTrue(out["municipal_batch_passed"])
        self.assertFalse(out["all_private_source_geo_attestations_passed"])
        self.assertFalse(out["in_memory_rehearsal_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertIn("one_or_more_private_attestations_invalid",
                      out["simulation_blockers"])

    def test_revocation_after_attestation_blocks_everything(self):
        def revoke(_, __, bundles, comments):
            comments.append({
                "id": 30001,
                "body": attestation_comment_line(bundles[2]["receipt"], "REVOKE"),
                "user": {"login": APPROVER, "type": "User"},
                "author_association": "OWNER",
                "created_at": STAMP,
            })
        out = run(variant=revoke)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertIn("private_owner_source_geo_attestation_revoked",
                      out["blocked_reason_counts"])

    def test_forged_owner_comment_is_not_attestation(self):
        def forge(_, __, bundles, comments):
            comments[0]["user"]["login"] = "unknown-collector"
        out = run(variant=forge)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertIn("private_owner_source_geo_attestation_absent",
                      out["blocked_reason_counts"])

    def test_unprivileged_owner_or_missing_token_rejected(self):
        ref, live, bundles, source, private, comments = scenario()
        def insufficient(url, token):
            if url == API + "/collaborators/Sarogal/permission":
                return {"permission": "read"}
            return private(url, token)
        self.assertEqual(run(gh=insufficient)["hypothetical_in_memory_additions"], 0)
        self.assertEqual(run(token=None)["hypothetical_in_memory_additions"], 0)

    def test_old_future_or_missing_authenticated_time_refused(self):
        for stamp in ("2026-10-30T00:00:00Z",
                      "2026-11-17T23:00:00Z", None):
            with self.subTest(stamp=stamp):
                def changed(_, __, bundles, comments):
                    comments[1]["created_at"] = stamp
                out = run(variant=changed)
                self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_changed_official_event_page_refused(self):
        ref, live, bundles, source, private, comments = scenario()
        changed_url = bundles[2]["review"]["candidates"][0]["official_event_url"]
        def changed(url):
            content = source(url)
            return content.replace("Gratuit.", "Tarif à confirmer.") if url == changed_url else content
        out = run(get=changed)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_changed_official_calendar_refused(self):
        ref, live, bundles, source, private, comments = scenario()
        cal = bundles[0]["review"]["candidates"][0]["calendar_url"]
        def changed(url):
            content = source(url)
            return content.replace("09h00", "13h00") if url == cal else content
        out = run(get=changed)
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_receipt_does_not_allow_source_substitution(self):
        def bad(_, __, bundles, ___):
            bundles[0]["receipt"]["venue_geo_url"] = "https://wrong.example/other"
        out = run(variant=bad)
        self.assertFalse(out["in_memory_rehearsal_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_registry_gps_moved_or_provenance_changed(self):
        for alteration in ("coords", "provenance"):
            with self.subTest(alteration=alteration):
                entry = deepcopy(SYNTHETIC_VENUE)
                if alteration == "coords":
                    entry["lat"] = 16.40000
                else:
                    entry["geo_source"] = "https://different-provider.example/point"
                out = run(records=[entry])
                self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_missing_real_gosier_registry_fails_closed(self):
        out = run(records=[])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertIn("independent_static_registry_missing_or_inconsistent",
                      out["blocked_reason_counts"])

    def test_external_official_site_unavailable_blocks_everything(self):
        def offline(url):
            raise OSError("offline")
        out = run(get=offline)
        self.assertFalse(out["municipal_batch_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertFalse(out["publication_ready"])

    def test_duplicate_id_in_batch_cannot_partially_advance(self):
        def repeat(_, __, bundles, ___):
            bundles[4] = deepcopy(bundles[0])
        out = run(variant=repeat)
        self.assertFalse(out["municipal_batch_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_cross_feed_duplicate_prevents_model_even_with_new_reviews(self):
        current = historical()
        cdocs, _, _ = sample_nine(public=current)
        cand = cdocs[1]["review"]["candidates"][0]
        current["events"].append({
            "id": "alternate-source-duplicate",
            "title": cand["title"], "category": "concert",
            "date_start": cand["date_start"],
            "date_end": cand["date_end"], "city": cand["city"],
            "venue": cand["venue"], "source_url": "https://alternate.example",
        })
        out = run(current=current)
        self.assertFalse(out["municipal_batch_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)
        self.assertEqual(out["current_events_preserved"], 549)

    def test_new_public_catalogue_invalidates_old_approvals(self):
        def changed(_, live, bundles, ___):
            live["updated_at"] = "2026-11-17T05:00:00+01:00"
        out = run(variant=changed)
        self.assertFalse(out["municipal_batch_passed"])
        self.assertEqual(out["hypothetical_in_memory_additions"], 0)

    def test_wrong_sha_pin_hard_refuses(self):
        with self.assertRaisesRegex(ValueError, "catalogue_changed"):
            run(cur_pin="f" * 64)

    def test_historical_prefix_cannot_be_changed_or_reordered(self):
        for mutation in ("change", "reorder"):
            with self.subTest(mutation=mutation):
                def bad(ref, live, bundles, comments):
                    if mutation == "change":
                        live["events"][0]["title"] = "tampered"
                    else:
                        live["events"][0], live["events"][1] = (
                            live["events"][1], live["events"][0]
                        )
                with self.assertRaisesRegex(
                    ValueError, "historical_catalogue_modified"
                ):
                    run(variant=bad)

    def test_missing_source_only_editorial_approval_for_unknown_access(self):
        ref, live, bundles, source, gh, comments = scenario(
            known_conditions=False
        )
        # All synthetic editorials are present: diagnostic is allowed.
        good = run(known_conditions=False)
        self.assertTrue(good["in_memory_rehearsal_passed"])
        def no_editorial(url, token):
            result = gh(url, token)
            if "/comments?" in url:
                return [c for c in result if "SOURCE-ONLY" not in c["body"]]
            return result
        bad = run(known_conditions=False, gh=no_editorial)
        self.assertEqual(bad["hypothetical_in_memory_additions"], 0)

    def test_mutating_callback_detected_and_no_release(self):
        ref, live, bundles, source, private, comments = scenario()
        def mutate(event):
            live["events"][0]["title"] = "mutated by callback"
            return True, "untrusted"
        with self.assertRaises(ValueError):
            inspect_attested_municipal_sync(
                ref, live, bundles, TODAY,
                reference_sha256=canonical_sha256(ref),
                current_sha256=canonical_sha256(live),
                token="test-only-token", source_get=source,
                github_get=private, geo_check=mutate,
                registry=[deepcopy(SYNTHETIC_VENUE)], now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
