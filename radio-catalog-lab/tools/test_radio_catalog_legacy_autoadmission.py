#!/usr/bin/env python3
"""Regression tests: legacy admission requires independently pinned evidence."""
from __future__ import annotations
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from radio_catalog_guard import validate_catalog


def station(index, *, decision="legacy_preserved", state="active", stream="verified"):
    return {
        "go_station_id": f"go-station-{index:06d}",
        "display_name": f"Old radio {index}",
        "country_code": "FR",
        "genres": ["Metal"],
        "tags": ["heavy metal"],
        "homepage": f"https://radio{index}.example.org/",
        "radio_browser_uuids": [{"uuid": f"old-uuid-{index}", "state": "historical"}],
        "legacy_aliases": [f"old-uuid-{index}"],
        "status": {"state": state, "reason_code":
                    "two_pass_audio_probe_unavailable" if state == "quarantined"
                    else None, "changed_at": "2026-11-22T20:00:00Z"},
        "streams": [{"stream_id": "mp3", "url": f"https://example.org/stream{index}",
                     "priority": 0, "protocol": "https", "codec": "mp3",
                     "bitrate_kbps": 128, "state": stream}],
        "logo": None,
        "editorial": {"admission_state": decision, "reviewed_at": None,
                      "evidence_refs": [f"v64-test:{index}"]},
    }


def document(stations, *, sequence=2):
    return {"schema_version": 1, "catalog_id": "grosses-ondes-radio",
            "release_sequence": sequence, "generated_at": "2026-11-22T20:00:00Z",
            "stations": stations, "tombstones": []}


def trusted(index):
    return {f"go-station-{index:06d}": {
        "uuid": f"old-uuid-{index}", "name": f"Old radio {index}",
        "evidence_ref": f"v64-test:{index}",
    }}


class LegacyAutoAdmissionTests(unittest.TestCase):
    def test_shipped_legacy_can_be_admitted_without_forged_manual_review(self):
        station_row = station(1)
        self.assertIsNone(station_row["editorial"]["reviewed_at"])
        self.assertEqual(validate_catalog(document([station_row]), mode="publish",
                                          previous=document([station_row], sequence=1),
                                          trusted_legacy=trusted(1)), [])

    def test_legacy_claim_without_external_pinned_provenance_is_denied(self):
        fixture = document([station(1)])
        prev = document([station(2)], sequence=1)
        self.assertTrue(any("trusted historic" in x for x in
            validate_catalog(fixture, mode="publish", previous=prev)))
        bogus = trusted(1)
        bogus["go-station-000001"]["uuid"] = "old-uuid-999"
        self.assertTrue(validate_catalog(fixture, mode="publish",
                                         previous=prev, trusted_legacy=bogus))

    def test_new_radio_cannot_inherit_anothers_name_or_alias(self):
        row = station(1)
        row["display_name"] = "My fraudulent new radio"
        self.assertTrue(validate_catalog(document([row]), mode="publish",
                                         previous=document([station(2)], sequence=1),
                                         trusted_legacy=trusted(1)))

    def test_failed_stream_can_be_kept_quarantined_only_with_real_failure_evidence(self):
        failed = station(1, state="quarantined", stream="candidate")
        prior = document([station(2)], sequence=1)
        catalog = document([failed])
        self.assertTrue(validate_catalog(catalog, mode="publish",
                                         previous=prior, trusted_legacy=trusted(1)))
        self.assertEqual(validate_catalog(catalog, mode="publish",
                                          previous=prior, trusted_legacy=trusted(1),
                                          failed_audio_go_ids={"go-station-000001"}), [])

    def test_active_legacy_never_bypasses_verified_stream_check(self):
        candidate = document([station(1, stream="candidate")])
        issues = validate_catalog(candidate, mode="publish",
                                  previous=document([station(2)], sequence=1),
                                  trusted_legacy=trusted(1))
        self.assertTrue(any("no verified stream" in x for x in issues))

    def test_legacy_auto_admission_does_not_permit_retired_tombstones(self):
        retired = station(1, state="retired", stream="candidate")
        result = validate_catalog(document([retired]), mode="publish",
                                  previous=document([station(2)], sequence=1),
                                  trusted_legacy=trusted(1),
                                  failed_audio_go_ids={"go-station-000001"})
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
