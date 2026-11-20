"""Isolated offline contract tests for the release-1 radio qualification queue."""
from __future__ import annotations

import copy
import hashlib
import unittest

from radio_catalog_qualification_queue import (
    build_queue, evidence_index, media_class,
)

U1 = "00000000-0000-4000-8000-000000000001"
U2 = "00000000-0000-4000-8000-000000000002"
U3 = "00000000-0000-4000-8000-000000000003"
MP3 = "https://example.org/live.mp3"
HLS = "https://example.org/radio.m3u8"
AAC = "https://example.org/live.aac"


def station(go_id="go-station-000001", uid=U1, codec="MP3", url=MP3):
    return {
        "go_station_id": go_id, "display_name": "Heavy Legacy",
        "country_code": "FR",
        "legacy_aliases": [uid],
        "radio_browser_uuids": [{"uuid": uid, "state": "current"}],
        "streams": [{"stream_id": "primary", "url": url,
                     "codec": codec, "state": "candidate"}],
        "editorial": {"admission_state": "legacy_preserved"},
    }


def catalog(*stations):
    return {"schema_version": 1, "stations": list(stations), "tombstones": []}


def candidate(uid=U2, *, name="New AAC Metal", codec="AAC", url=AAC, risk=False):
    return {
        "stationuuid": uid, "name": name, "countrycode": "FR",
        "status": "candidate_requires_qualification",
        "streamUrl": url, "codec": codec, "duplicateIdentityRisk": risk,
    }


def discovery(*items):
    return {"schemaVersion": 1, "scanDate": "2026-11-20",
            "publicationAllowed": False, "candidates": list(items)}


def evidence(uid=U1, url=MP3, dates=None):
    dates = dates or ["2026-11-18", "2026-11-20"]
    return {
        "schemaVersion": 1, "observationDate": "2026-11-20",
        "publicationAllowed": False, "technicallyQualifiedCount": 0,
        "records": [{
            "stationuuid": uid,
            "streamSha256": hashlib.sha256(url.encode()).hexdigest(),
            "audioEvidenceDates": dates, "sustainedTransportDates": dates,
            "frameChainDates": dates, "decodedPcmDates": dates,
            "technicalQualified": False, "publicationAllowed": False,
        }],
    }


class QualificationQueueTests(unittest.TestCase):
    def test_prioritizes_legacy_mp3_then_new_aac_before_hls(self):
        report = build_queue(catalog(
            station(), station("go-station-000002", U3, "HLS", HLS)),
            discovery(candidate()))
        self.assertEqual(report["historicalStationCount"], 2)
        self.assertEqual(report["preservedHistoricalStreamCount"], 2)
        self.assertEqual(report["discoveredCandidateCount"], 1)
        self.assertEqual(report["queueCount"], 3)
        self.assertEqual([r["transportLane"] for r in report["items"]],
                         ["mp3_aac_first", "mp3_aac_first", "hls_deferred"])
        self.assertEqual(report["transportLaneCounts"]["hls_deferred"], 1)
        self.assertEqual(report["deletedCount"], 0)

    def test_legacy_is_not_lost_when_not_seen_today(self):
        result = build_queue(catalog(station()), discovery())
        self.assertEqual(result["preservedHistoricalStreamCount"], 1)
        self.assertEqual(result["items"][0]["goStationId"], "go-station-000001")
        self.assertEqual(result["items"][0]["identityStatus"], "legacy_preserved")

    def test_new_uuid_is_allowed_into_review_without_static_allowlist(self):
        result = build_queue(catalog(station()), discovery(candidate()))
        item = [x for x in result["items"] if x["source"] == "discovery"][0]
        self.assertEqual(item["stationuuid"], U2)
        self.assertEqual(item["identityStatus"], "unmapped_candidate")
        self.assertFalse(item["editoriallyApproved"])

    def test_possible_duplicate_never_becomes_an_alias_or_approval(self):
        result = build_queue(catalog(station()), discovery(
            candidate(name="Heavy Legacy", url=MP3, risk=True)))
        row = result["items"][1]
        self.assertEqual(row["identityStatus"], "possible_variant_or_duplicate")
        self.assertIn("identity_review", row["nextAction"])
        self.assertIsNone(row["goStationId"])
        self.assertIs(row["publicationAllowed"], False)

    def test_hls_not_automatically_rejected_or_made_publishable(self):
        result = build_queue(catalog(station(codec="HLS", url=HLS)), discovery())
        row = result["items"][0]
        self.assertEqual(row["nextAction"], "separate_hls_verification_lane")
        self.assertFalse(row["technicalQualified"])
        self.assertEqual(result["admittedCount"], 0)

    def test_matching_multiday_pcm_only_creates_review_not_verified(self):
        result = build_queue(catalog(station()), discovery(), evidence())
        row = result["items"][0]
        self.assertEqual(row["decodedEvidenceDays"], 2)
        self.assertEqual(row["nextAction"], "review_multi_day_pcm_and_station_identity")
        self.assertFalse(row["technicalQualified"])
        self.assertFalse(row["editoriallyApproved"])

    def test_stale_stream_sha_does_not_inherit_previous_evidence(self):
        old = evidence(url="https://example.org/old.mp3")
        row = build_queue(catalog(station()), discovery(), old)["items"][0]
        self.assertEqual(row["audioEvidenceDays"], 0)
        self.assertEqual(row["nextAction"], "bounded_multiday_mp3_aac_probes")

    def test_rejects_proof_that_claims_technical_certification(self):
        bad = evidence()
        bad["records"][0]["technicalQualified"] = True
        with self.assertRaisesRegex(ValueError, "cannot authorize"):
            build_queue(catalog(station()), discovery(), bad)

    def test_rejects_forced_publication_of_discovery(self):
        bad = discovery(candidate())
        bad["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            build_queue(catalog(station()), bad)

    def test_rejects_duplicate_go_ids(self):
        with self.assertRaises(ValueError):
            build_queue(catalog(station(), station(uid=U3)), discovery())

    def test_rejects_future_or_replayed_evidence_dates(self):
        bad = evidence()
        bad["records"][0]["audioEvidenceDates"] += ["2026-11-18"]
        with self.assertRaises(ValueError):
            evidence_index(bad)
        bad = evidence()
        bad["records"][0]["decodedPcmDates"] = ["2026-11-21"]
        with self.assertRaises(ValueError):
            evidence_index(bad)

    def test_preserves_alias_and_stream_identity_without_raw_url_in_report(self):
        result = build_queue(catalog(station()), discovery(candidate()))
        encoded = str(result)
        self.assertNotIn("https://", encoded)
        self.assertNotIn("example.org", encoded)
        for item in result["items"]:
            self.assertEqual(len(item["streamSha256"]), 64)
            self.assertFalse(item["publicationAllowed"])

    def test_recognizes_mp3_aac_hls_by_transport_hint(self):
        self.assertEqual(media_class("AAC+", "https://x.org/stream"), "mp3_aac_first")
        self.assertEqual(media_class("unknown", "https://x.org/a.m3u8"), "hls_deferred")
        self.assertEqual(media_class(None, "https://x.org/live"), "other_needs_format_check")


if __name__ == "__main__":
    unittest.main()
