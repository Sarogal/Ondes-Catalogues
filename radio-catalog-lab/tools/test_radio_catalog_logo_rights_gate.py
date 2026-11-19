"""Synthetic, network-free tests for v1 logo rights and stream-policy gate."""
import copy
import unittest

from radio_catalog_logo_rights_gate import audit_logo_rights


def fixtures():
    urls = [
        "https://station.example.org/a.png",
        "https://another.example.org/b.jpg",
    ]
    pilot = {
        "schema_version": 1,
        "entries": [
            {"source_url": urls[0], "go_station_ids": ["go-station-000001"]},
            {"source_url": urls[1], "go_station_ids": ["go-station-000002"]},
        ],
    }
    network = {
        "schema_version": 1,
        "catalog_signed": False,
        "production_modified": False,
        "approved_logo_count": 0,
        "matching_sha256_across_two_attempts": 1,
        "observations": [
            {
                "source_url": urls[0],
                "historical_go_station_ids": ["go-station-000001"],
                "sha256_stable_across_two_requests": True,
                "first_attempt": {
                    "sha256": "a" * 64, "byte_size": 100,
                    "mime_type": "image/png", "width": 500, "height": 500,
                },
                "second_attempt": {
                    "sha256": "a" * 64, "byte_size": 100,
                    "mime_type": "image/png", "width": 500, "height": 500,
                },
            },
            {
                "source_url": urls[1],
                "historical_go_station_ids": ["go-station-000002"],
                "sha256_stable_across_two_requests": False,
                "first_attempt": {"error_type": "gaierror"},
                "second_attempt": {"error_type": "OSError"},
            },
        ],
    }
    rights = {
        "schema_version": 1,
        "ledger_kind": "THIRD_PARTY_RADIO_LOGO_RIGHTS_REGISTER",
        "approved_logos": 0,
        "permission_replies_received": 0,
        "emails_sent": 0,
        "catalog_publication_authorized": False,
        "records": [
            {
                "source_url": urls[0],
                "go_station_ids": ["go-station-000001"],
                "rights_state": "PROHIBITS_NEW_THIRD_PARTY_APPS",
                "rights_evidence_urls": ["https://station.example.org/legal/tos"],
                "source_sha256_observed_only": "a" * 64,
                "artifact_sha_technical_status": "TWO_MATCHING_REMOTE_SHA_NOT_REHOSTED",
                "may_publish_immutable_logo": False,
                "catalog_admission_authorized": False,
                "permission_evidence_id": None,
                "contact_status": "NOT_CONTACTED",
                "station_identity_review": "PENDING",
                "visual_fit_review": "PENDING",
                "stream_terms_review": "URGENT_SEPARATE_REVIEW",
            },
            {
                "source_url": urls[1],
                "go_station_ids": ["go-station-000002"],
                "rights_state": "PERMISSION_NOT_DOCUMENTED",
                "rights_evidence_urls": [],
                "source_sha256_observed_only": None,
                "artifact_sha_technical_status": "NO_RELIABLE_BYTES",
                "may_publish_immutable_logo": False,
                "catalog_admission_authorized": False,
                "permission_evidence_id": None,
                "contact_status": "NOT_CONTACTED",
                "station_identity_review": "PENDING",
                "visual_fit_review": "PENDING",
                "stream_terms_review": "SEPARATE_REVIEW",
            },
        ],
    }
    return pilot, network, rights


class StrictLogoRightsGateTest(unittest.TestCase):
    def test_two_sources_never_gain_rehosting_rights_from_verified_sha(self):
        p, n, r = fixtures()
        result = audit_logo_rights(p, n, r)
        self.assertEqual(result["status"], "STRICT_V1_RIGHTS_GATE_BLOCKS_ALL_PUBLICATION")
        self.assertEqual(result["reviewed_source_urls"], 2)
        self.assertEqual(result["historical_go_station_ids_affected"], 2)
        self.assertEqual(result["repeated_remote_sha_sources"], 1)
        self.assertEqual(result["rights_authorized_for_rehosting"], 0)
        self.assertEqual(result["stream_terms_requiring_separate_review"], 1)
        self.assertFalse(result["ready_to_sign_catalog"])
        self.assertEqual(
            result["rights_status_counts"],
            {"PERMISSION_NOT_DOCUMENTED": 1, "PROHIBITS_NEW_THIRD_PARTY_APPS": 1},
        )

    def test_rights_state_cannot_be_upgraded_without_new_schema(self):
        p, n, r = fixtures()
        r["records"][0]["rights_state"] = "WRITTEN_PERMISSION_GRANTED"
        with self.assertRaisesRegex(ValueError, "rights-state"):
            audit_logo_rights(p, n, r)

    def test_forged_permission_reference_still_refused(self):
        p, n, r = fixtures()
        r["records"][0]["permission_evidence_id"] = "user-says-approved"
        with self.assertRaisesRegex(ValueError, "editorial acceptance"):
            audit_logo_rights(p, n, r)

    def test_false_publish_flag_fails_closed(self):
        p, n, r = fixtures()
        r["records"][0]["may_publish_immutable_logo"] = True
        with self.assertRaisesRegex(ValueError, "editorial acceptance"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["catalog_publication_authorized"] = True
        with self.assertRaisesRegex(ValueError, "v1 ledger"):
            audit_logo_rights(p, n, r)

    def test_cannot_claim_contact_was_sent_or_reply_received(self):
        p, n, r = fixtures()
        r["emails_sent"] = 1
        with self.assertRaisesRegex(ValueError, "v1 ledger"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["records"][1]["contact_status"] = "REPLIED"
        with self.assertRaisesRegex(ValueError, "editorial acceptance"):
            audit_logo_rights(p, n, r)

    def test_explicit_prohibition_requires_official_terms_link(self):
        p, n, r = fixtures()
        r["records"][0]["rights_evidence_urls"] = []
        with self.assertRaisesRegex(ValueError, "official source"):
            audit_logo_rights(p, n, r)

    def test_restriction_evidence_cannot_be_http_or_userinfo(self):
        p, n, r = fixtures()
        r["records"][0]["rights_evidence_urls"] = ["http://bad.example.org/"]
        with self.assertRaisesRegex(ValueError, "rights source"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["records"][0]["rights_evidence_urls"] = ["https://u:p@station.example.org/"]
        with self.assertRaisesRegex(ValueError, "rights source"):
            audit_logo_rights(p, n, r)

    def test_policy_block_must_prompt_separate_stream_review(self):
        p, n, r = fixtures()
        r["records"][0]["stream_terms_review"] = "SEPARATE_REVIEW"
        with self.assertRaisesRegex(ValueError, "stream-policy"):
            audit_logo_rights(p, n, r)

    def test_source_url_or_go_id_crossing_is_rejected(self):
        p, n, r = fixtures()
        r["records"][0]["go_station_ids"] = ["go-station-000002"]
        with self.assertRaisesRegex(ValueError, "identity"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["records"][0]["source_url"] = "https://other.example.org/c.png"
        with self.assertRaisesRegex(ValueError, "not identical"):
            audit_logo_rights(p, n, r)

    def test_same_go_id_cannot_appear_on_two_sources(self):
        p, n, r = fixtures()
        p["entries"][1]["go_station_ids"] = ["go-station-000001"]
        n["observations"][1]["historical_go_station_ids"] = ["go-station-000001"]
        r["records"][1]["go_station_ids"] = ["go-station-000001"]
        with self.assertRaisesRegex(ValueError, "assigned"):
            audit_logo_rights(p, n, r)

    def test_sha_drift_and_fabricated_sha_are_rejected(self):
        p, n, r = fixtures()
        n["observations"][0]["second_attempt"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "Technical evidence"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["records"][1]["source_sha256_observed_only"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "Unavailable"):
            audit_logo_rights(p, n, r)

    def test_never_trust_unsigned_approved_network_catalog(self):
        p, n, r = fixtures()
        n["catalog_signed"] = True
        with self.assertRaisesRegex(ValueError, "unsigned proof"):
            audit_logo_rights(p, n, r)

    def test_stability_count_must_match_proven_rows(self):
        p, n, r = fixtures()
        n["matching_sha256_across_two_attempts"] = 2
        with self.assertRaisesRegex(ValueError, "summary count"):
            audit_logo_rights(p, n, r)

    def test_source_missing_or_duplicate_is_rejected(self):
        p, n, r = fixtures()
        r["records"].pop()
        with self.assertRaisesRegex(ValueError, "not identical"):
            audit_logo_rights(p, n, r)
        p, n, r = fixtures()
        r["records"].append(copy.deepcopy(r["records"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_logo_rights(p, n, r)


if __name__ == "__main__":
    unittest.main()
