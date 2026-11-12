"""Adversarial unit tests: diagnostic remains read-only and private."""
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_qualification_rootcause import (
    explicit_reason, probe_uid_in_index, rootcause_audit, public_summary,
)

TODAY = date(2026, 11, 12)


def lead(uid, coll="opendatasoft-index", date_start="2027-02-01"):
    return {"external_id": str(uid), "date_start": date_start,
            "collector": coll,
            "source_url": "https://openagenda.com/municipal/events/" + str(uid)}


def catalogue():
    return {"events": [{"id": "original"}],
            "updated_at": "2026-11-12T20:30:28+01:00"}


class BoundedReasonTests(unittest.TestCase):
    def test_exact_canonical_and_audience_issues(self):
        samples = {
            "Destination familiale musicale insuffisamment explicite":
                "audience_or_music_signal_absent",
            "URL canonique différente": "canonical_pair_unreviewed",
            "UID absent ou non unique dans l'index": "ods_uid_unresolved",
            "âge minimum non confirmé": "official_age_unconfirmed",
            "date complète non confirmée sur la fiche officielle":
                "official_date_unconfirmed",
            "HTTP Error 429: Too Many Requests": "ods_http_429",
            "HTTP Error 503: Service Unavailable": "ods_http_5xx",
        }
        for msg, code in samples.items():
            with self.subTest(reason=code):
                self.assertEqual(explicit_reason({
                    "status": "deferred", "reason": msg}), code)

    def test_arbitrary_private_text_never_survives(self):
        self.assertEqual(explicit_reason({
            "status": "deferred",
            "reason": "https://private.example/abc token=never-export-this"}),
            "other")
        self.assertEqual(explicit_reason({
            "status": "already_published", "reason": ""}), "already_published")


class IndexProbeTests(unittest.TestCase):
    def test_absent_nonunique_and_unique_are_distinct(self):
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"results": []}), "uid_absent")
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"results": [{"uid": "123"},
                                                {"uid": "123"}]}),
                         "uid_nonunique")
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"results": [{"uid": "123"}]}),
                         "uid_unique")
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"results": [{"uid": "987"}]}),
                         "unexpected_uid")

    def test_http_and_schema_fail_closed(self):
        def fail(url):
            raise HTTPError(url, 429, "throttle", {}, BytesIO())
        self.assertEqual(probe_uid_in_index("123", get=fail), "http_429")
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"results": [12]}),
                         "invalid_json_or_schema")
        self.assertEqual(probe_uid_in_index(
            "123", get=lambda url: {"not_results": []}),
                         "invalid_json_or_schema")
        with self.assertRaises(ValueError):
            probe_uid_in_index("1 OR 1=1", get=lambda url: None)


class RootcauseAuditTests(unittest.TestCase):
    def test_complete_exact_uid_day_report_without_identifiers(self):
        raw = [lead(11), lead(11, "openagenda-v2"),
               lead(12), lead(13)]
        distinct = [raw[0], raw[2], raw[3]]

        def review(batch, baseline, published, day, limit, slot):
            self.assertEqual(len(batch), 4)
            return ({"safe_to_publish": False, "additions": []},
                    {"mode": "preview_no_public_write",
                     "date": str(day),
                     "eligible_with_reviewed_venue": 3,
                     "checked": 3, "accepted_preflight": 0,
                     "details": [
                         {"status": "deferred",
                          "source_url": raw[0]["source_url"],
                          "date": raw[0]["date_start"],
                          "reason": "UID absent ou non unique dans l'index"},
                         {"status": "deferred",
                          "source_url": raw[2]["source_url"],
                          "date": raw[2]["date_start"],
                          "reason": "URL canonique différente"},
                         {"status": "deferred",
                          "source_url": raw[3]["source_url"],
                          "date": raw[3]["date_start"],
                          "reason": "Destination familiale musicale insuffisamment explicite"},
                     ]})
        probed = []
        def probe(uid):
            probed.append(uid)
            return "uid_absent"
        with patch("ptitesondes_qualification_rootcause.unique_review_candidates",
                   return_value=(distinct, 4, 1, 0)), patch(
                   "ptitesondes_qualification_rootcause.permitted",
                   return_value=True):
            report = rootcause_audit(raw, {}, catalogue(), TODAY,
                                     review=review, index_probe=probe)
        self.assertEqual(probed, ["11"])
        self.assertEqual(report["checked"], 3)
        self.assertEqual(report["prevalidated"], 0)
        self.assertEqual(report["ods_uid_probe_codes"], {"uid_absent": 1})
        self.assertEqual(report["failure_codes"], {
            "ods_uid_unresolved": 1, "canonical_pair_unreviewed": 1,
            "audience_or_music_signal_absent": 1})
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["private_approvals"], 0)
        shown = json.dumps(report, ensure_ascii=False)
        for forbidden in ["https://", "11", "token=", "http://", "Matin câlin"]:
            # '11' can occur in the timestamp, so only require no event UID fields
            if forbidden != "11":
                self.assertNotIn(forbidden, shown)
        self.assertNotIn("source_url", shown)
        self.assertNotIn("external_id", shown)
        public = json.dumps(public_summary(report))
        self.assertNotIn("failure_codes", public)
        self.assertNotIn("reason_groups", public)

    def test_incomplete_batch_cannot_produce_a_report(self):
        raw = [lead(123)]
        def bad_review(*args, **kwargs):
            return {"safe_to_publish": False, "additions": []}, {
                "date": str(TODAY), "mode": "preview_no_public_write",
                "eligible_with_reviewed_venue": 1, "checked": 0,
                "accepted_preflight": 0, "details": []}
        with patch("ptitesondes_qualification_rootcause.unique_review_candidates",
                   return_value=(raw, 1, 0, 0)), patch(
                   "ptitesondes_qualification_rootcause.permitted",
                   return_value=True):
            with self.assertRaises(ValueError):
                rootcause_audit(raw, {}, catalogue(), TODAY, review=bad_review)

    def test_public_allowlist_rejects_injection(self):
        self.assertEqual(public_summary({
            "schema": "ptitesondes.private_outings_rootcause.v1",
            "checked": 5, "backlog_total": True,
            "source_url": "https://secret.example"}), {"checked": 5})
        with self.assertRaises(ValueError):
            public_summary({"schema": "untrusted", "checked": 5})


if __name__ == "__main__":
    unittest.main()
