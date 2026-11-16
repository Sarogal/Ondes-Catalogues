"""Offline adversarial suite: private owner-attested evidence is NOT publishing."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_municipal_source_geo_attestation import (
    SCHEMA, RECEIPT_SCHEMA, attestation_comment_line,
    inspect_source_geo_attestation,
)
from ptitesondes_municipal_human_decision import (
    API, APPROVER, canonical_digest, html_digest, request_digest,
)
from ptitesondes_municipal_preflight import municipal_calendar_url
from test_ptitesondes_municipal_admission import fixture, github_for
from test_ptitesondes_municipal_preflight import CALENDAR
from test_ptitesondes_nonmusic_release_contract import (
    TODAY, URL, private_review, private_access,
)

NOW = datetime(2026, 11, 16, 22, 0, 0, tzinfo=timezone.utc)
STAMP = "2026-11-16T20:00:00Z"
SYNTHETIC_VENUE = {
    # These URLs/coordinates are in an injected fixture, NOT merged #305.
    "city": "Le Gosier",
    "aliases": ["Médiathèque Raoul Georges Nicolo"],
    "lat": 16.20547,
    "lng": -61.4895,
    "official": "https://ccfr.bnf.fr/portailccfr/ark:/16871/0027125",
    "geo_source": "https://mapcarta.com/fr/W125054083",
}


def receipt_for(doc, c, a, manifest, official, record, calendar=CALENDAR):
    return {
        "schema": RECEIPT_SCHEMA,
        "mode": "request_private_source_geo_attestation",
        "review_id": c["review_id"],
        "pr_number": manifest["pr_number"],
        "head_sha": manifest["head_sha"],
        "manifest_sha256": request_digest(manifest),
        "candidate_sha256": canonical_digest(c),
        "access_sha256": canonical_digest(a),
        "catalogue_sha256": canonical_digest(doc),
        "event_html_sha256": html_digest(official),
        "calendar_html_sha256": html_digest(calendar),
        "calendar_url": municipal_calendar_url(TODAY.replace(day=25)),
        "venue_registry_sha256": canonical_digest(record),
        "venue_official_url": record["official"],
        "venue_geo_url": record["geo_source"],
    }


def scenario(*, explicit=True, approval="APPROVE", editorial="ABSENT",
             attest="ATTEST", actor=APPROVER, association="OWNER",
             when=STAMP, permission="admin", receipt_change=None,
             html_change=None, calendar_change=None, venue_change=None,
             use_registry=True, geo=True, token="test-token",
             change_pr_head=False):
    doc, c, a, manifest, original = fixture(explicit=explicit)
    venue = deepcopy(SYNTHETIC_VENUE)
    receipt = receipt_for(doc, c, a, manifest, original, venue)
    if receipt_change is not None:
        receipt_change(receipt)
    if venue_change is not None:
        venue_change(venue)
    original_get = github_for(
        manifest, decision=approval, permission=permission,
        editorial=editorial,
    )
    calendar = CALENDAR if calendar_change is None else calendar_change(CALENDAR)
    html = original if html_change is None else html_change(original)

    def get_public(url):
        pages = {
            URL: html,
            municipal_calendar_url(TODAY.replace(day=25)): calendar,
        }
        return pages[url]

    def get_private(url, secret):
        if url == API + "/issues/88/comments?per_page=100&page=1":
            comments = list(original_get(url, secret))
            if attest is not None:
                comments.append({
                    "id": 105,
                    "body": attestation_comment_line(receipt, "ATTEST"),
                    "user": {"login": actor, "type": "User"},
                    "author_association": association,
                    "created_at": when,
                })
            if attest == "REVOKE":
                comments.append({
                    "id": 106,
                    "body": attestation_comment_line(receipt, "REVOKE"),
                    "user": {"login": APPROVER, "type": "User"},
                    "author_association": "OWNER",
                    "created_at": when,
                })
            return comments
        response = original_get(url, secret)
        if change_pr_head and url == API + "/pulls/88":
            response = deepcopy(response)
            response["head"]["sha"] = "f" * 40
        return response

    return inspect_source_geo_attestation(
        doc, private_review(c), private_access(a), manifest, receipt, TODAY,
        token=token, source_get=get_public, github_get=get_private,
        geo_check=lambda event: (geo, "synthetic only"),
        registry=[venue] if use_registry else None,
        now=NOW,
    )


class PrivateSourceGeoAttestationTests(unittest.TestCase):
    def test_owner_attests_current_exact_receipt_but_publication_stays_blocked(self):
        with patch("merge_policy.merge", side_effect=AssertionError(
            "publisher must never be called"
        )):
            result = scenario()
        self.assertEqual(result["schema"], SCHEMA)
        self.assertTrue(result["authenticated_private_attestation_passed"])
        self.assertTrue(result["official_event_and_calendar_rechecked"])
        self.assertTrue(result["registry_checked_against_versioned_static_entry"])
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["github_comment_timestamp_required"])
        self.assertTrue(result["attestation_is_not_digital_signature"])
        self.assertTrue(result["geo_provider_not_refetched"])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["approval_granted_to_publisher"])
        self.assertEqual(result["public_writes"], 0)
        for forbidden in ("events", "patch", "additions", "token",
                          "review_id", "candidate", "source_url"):
            self.assertNotIn(forbidden, result)

    def test_absent_or_revoked_attestation_rejected(self):
        for decision, reason in (
            (None, "private_owner_source_geo_attestation_absent"),
            ("REVOKE", "private_owner_source_geo_attestation_revoked"),
        ):
            with self.subTest(decision=decision):
                out = scenario(attest=decision)
                self.assertFalse(out["authenticated_private_attestation_passed"])
                self.assertIn(reason, out["blockers"])

    def test_forged_owner_or_unprivileged_comment_rejected(self):
        for changes in (
            {"actor": "not-the-owner"},
            {"association": "CONTRIBUTOR"},
            {"permission": "read"},
        ):
            with self.subTest(changes=changes):
                out = scenario(**changes)
                self.assertFalse(out["authenticated_private_attestation_passed"])

    def test_stale_future_or_absent_github_server_timestamp_rejected(self):
        for stamp in (
            "2026-10-30T20:00:00Z",
            "2026-11-17T20:00:00Z",
            None,
            "2026-11-16",
        ):
            with self.subTest(stamp=stamp):
                out = scenario(when=stamp)
                self.assertIn(
                    "github_attestation_stale_or_future" if stamp is not None
                    and "T" in stamp else "github_attestation_timestamp_missing",
                    out["blockers"]
                )

    def test_missing_event_approval_cannot_be_replaced_by_attestation(self):
        for approval in ("ABSENT", "REVOKE"):
            out = scenario(approval=approval)
            self.assertFalse(out["authenticated_private_attestation_passed"])
            self.assertIn("prior_private_admission_not_verified", out["blockers"])

    def test_unknown_access_needs_distinct_source_only_decision(self):
        rejected = scenario(explicit=False)
        self.assertIn("prior_private_admission_not_verified", rejected["blockers"])
        simulated_owner_decision = scenario(
            explicit=False, editorial="SOURCE_ONLY"
        )
        self.assertTrue(simulated_owner_decision[
            "authenticated_private_attestation_passed"
        ])
        self.assertFalse(simulated_owner_decision["publication_ready"])

    def test_changed_event_html_not_approved(self):
        out = scenario(
            html_change=lambda raw: raw.replace(
                "Gratuit.", "Détail tarifaire différent."
            )
        )
        self.assertIn("prior_private_admission_not_verified", out["blockers"])
        self.assertIn(
            "source_calendar_or_registry_receipt_mismatch", out["blockers"]
        )

    def test_changed_calendar_rejected_even_with_same_organizer_page(self):
        out = scenario(calendar_change=lambda raw: raw.replace(
            "09h30", "10h30"
        ))
        self.assertIn("prior_private_admission_not_verified", out["blockers"])
        self.assertIn(
            "source_calendar_or_registry_receipt_mismatch", out["blockers"]
        )

    def test_forged_receipt_or_different_pr_head_rejected(self):
        altered = scenario(receipt_change=lambda receipt:
                           receipt.__setitem__("head_sha", "f" * 40))
        self.assertIn(
            "source_calendar_or_registry_receipt_mismatch", altered["blockers"]
        )
        pr_changed = scenario(change_pr_head=True)
        self.assertIn("prior_private_admission_not_verified", pr_changed["blockers"])

    def test_registry_coordinates_or_provenance_change_rejected(self):
        for change in (
            lambda v: v.__setitem__("lat", 16.30000),
            lambda v: v.__setitem__("geo_source", "https://maps.other.example/new"),
            lambda v: v.__setitem__("geo_source", v["official"]),
            lambda v: v.__setitem__("geo_source", "http://mapcarta.com/fr/W125054083"),
        ):
            with self.subTest(change=change):
                out = scenario(venue_change=change)
                self.assertFalse(out["authenticated_private_attestation_passed"])

    def test_real_branch_lacks_gosier_static_record_so_default_must_fail(self):
        # The separate #305 GPS branch is still a draft: do not pretend its
        # immutable entry was integrated in the #335 parent.
        result = scenario(use_registry=False)
        self.assertIn(
            "independent_static_registry_missing_or_inconsistent",
            result["blockers"]
        )

    def test_source_geo_check_cannot_override_bad_location(self):
        out = scenario(geo=False)
        self.assertIn("prior_private_admission_not_verified", out["blockers"])

    def test_no_token_or_unavailable_pr_cannot_attest(self):
        missing = scenario(token=None)
        self.assertIn("prior_private_admission_not_verified", missing["blockers"])
        invalid_head = scenario(change_pr_head=True)
        self.assertFalse(invalid_head["authenticated_private_attestation_passed"])

    def test_receipt_digest_still_requires_real_owner_comment(self):
        # Hashing a self-provided receipt is NOT a signature or an approval.
        out = scenario(attest=None)
        self.assertFalse(out["authenticated_private_attestation_passed"])
        self.assertTrue(out["attestation_is_not_digital_signature"])

    def test_missing_receipt_property_fails_closed(self):
        result = scenario(
            receipt_change=lambda doc: doc.pop("venue_registry_sha256")
        )
        self.assertIn(
            "source_calendar_or_registry_receipt_mismatch", result["blockers"]
        )

    def test_unexpected_extra_receipt_property_fails_closed(self):
        result = scenario(receipt_change=lambda r: r.update({"approved": True}))
        self.assertIn(
            "source_calendar_or_registry_receipt_mismatch", result["blockers"]
        )


if __name__ == "__main__":
    unittest.main()
