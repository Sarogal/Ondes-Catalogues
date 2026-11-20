"""End-to-end offline contract tests: real probe functions + multistream ledger."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import unittest

from radio_catalog_batch_evidence_bridge import consume_batches
from radio_catalog_probe_batch_plan import plan_batches
from radio_stream_technical_probe import ResponseSample, probe_candidates

U1 = "00000000-0000-4000-8000-000000000001"
U2 = "00000000-0000-4000-8000-000000000002"
U3 = "00000000-0000-4000-8000-000000000003"
URL1 = "https://example.org/station1.mp3"
URL2 = "https://example.org/station2.mp3"
ALT = "https://example.org/station1-alternate.mp3"
AUDIO = b"\xff\xfb\x90\x64" + b"\x00" * 80


def station(go, uid, *urls):
    return {
        "go_station_id": go, "display_name": go, "country_code": "FR",
        "legacy_aliases": [uid],
        "radio_browser_uuids": [{"uuid": uid, "state": "current"}],
        "streams": [{"stream_id": f"stream-{i}", "url": url,
                     "codec": "MP3", "state": "candidate"} for i, url in enumerate(urls)],
    }


def catalog(*stations):
    return {"schema_version": 1, "stations": list(stations), "tombstones": []}


def discovery(*candidates, date="2026-11-20"):
    return {
        "schemaVersion": 1, "scanDate": date,
        "publicationAllowed": False, "candidates": list(candidates),
    }


def found(uid=U3):
    return {
        "stationuuid": uid, "name": "New Rock Radio", "countrycode": "FR",
        "status": "candidate_requires_qualification",
        "streamUrl": "https://example.org/new.mp3", "codec": "MP3",
    }


def fake_request(url):
    # Uses the real existing probe's classification, no sockets.
    return ResponseSample(
        status=200, content_type="audio/mpeg", location="", body=AUDIO,
    )


def planned_report(batch, urls, date):
    candidates = []
    for item in batch["candidates"]:
        key = (item["stationuuid"], item["streamSha256"])
        url = urls[key]
        candidates.append({
            "stationuuid": item["stationuuid"],
            "name": "Synthetic Rock",
            "status": "needs_stream_check",
            "streamUrl": url,
        })
    return probe_candidates(
        discovery(*candidates, date=date), fake_request,
        limit=5, observation_day=dt.date.fromisoformat(date),
    )


def map_urls(*entries):
    return {
        (uid, hashlib.sha256(url.encode()).hexdigest()): url
        for uid, url in entries
    }


class RealProbeToStreamHistoryTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog(
            station("go-station-000001", U1, URL1),
            station("go-station-000002", U2, URL2),
        )
        self.discovery = discovery(found())
        self.urls = map_urls((U1, URL1), (U2, URL2),
                             (U3, "https://example.org/new.mp3"))

    def make(self, *, date="2026-11-20", daily=2, items=None, candidates=None):
        central = items if items is not None else self.catalog
        scan = candidates if candidates is not None else self.discovery
        plan = plan_batches(central, scan, day=date, max_daily=daily,
                            max_per_batch=1)
        reports = [planned_report(batch, self.urls, date)
                   for batch in plan["batches"]]
        return plan, reports

    def test_real_probe_two_batches_converge_into_one_stream_ledger(self):
        plan, reports = self.make(daily=2)
        self.assertEqual(plan["plannedProbeCount"], 2)
        self.assertEqual(len(plan["batches"]), 2)
        result = consume_batches(plan, reports)
        self.assertEqual(result["processedBatches"], 2)
        self.assertEqual(result["processedChecks"], 2)
        self.assertEqual(result["audioSampleObservations"], 2)
        self.assertEqual(len(result["streamEvidence"]["records"]), 2)
        self.assertTrue(all(r["audioEvidenceDates"] == ["2026-11-20"]
                            for r in result["streamEvidence"]["records"]))
        self.assertEqual(result["streamEvidence"]["streamHistoryMode"], "per_stream")
        self.assertEqual(result["technicallyQualifiedCount"], 0)
        self.assertFalse(result["publicationAllowed"])
        self.assertNotIn("https://", json.dumps(result))

    def test_second_day_accumulates_evidence_but_never_approves(self):
        plan, reports = self.make(daily=2)
        first = consume_batches(plan, reports)
        nxt_plan, nxt_reports = self.make(date="2026-11-21", daily=2)
        second = consume_batches(
            nxt_plan, nxt_reports, first["streamEvidence"],
        )
        self.assertEqual(second["processedChecks"], 2)
        self.assertTrue(any(len(r["audioEvidenceDates"]) >= 2
                            for r in second["streamEvidence"]["records"]))
        self.assertEqual(second["streamEvidence"]["technicallyQualifiedCount"], 0)
        self.assertFalse(second["publicationAllowed"])

    def test_stream_variants_keep_independent_dates(self):
        first_catalog = catalog(station("go-station-000001", U1, URL1))
        p1 = plan_batches(first_catalog, discovery(), day="2026-11-20",
                          max_daily=1, max_per_batch=1)
        old = consume_batches(p1, [planned_report(
            p1["batches"][0], self.urls, "2026-11-20",
        )])
        alternative = catalog(station("go-station-000001", U1, ALT))
        self.urls.update(map_urls((U1, ALT)))
        p2 = plan_batches(alternative, discovery(), day="2026-11-21",
                          max_daily=1, max_per_batch=1)
        changed = consume_batches(
            p2, [planned_report(p2["batches"][0], self.urls, "2026-11-21")],
            old["streamEvidence"],
        )
        observed = {r["streamSha256"]: r for r in changed["streamEvidence"]["records"]}
        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[hashlib.sha256(URL1.encode()).hexdigest()]["audioEvidenceDates"],
                         ["2026-11-20"])
        self.assertEqual(observed[hashlib.sha256(ALT.encode()).hexdigest()]["audioEvidenceDates"],
                         ["2026-11-21"])

    def test_rejects_wrong_stream_hash_in_report(self):
        plan, reports = self.make()
        reports[0]["checks"][0]["streamSha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            consume_batches(plan, reports)

    def test_rejects_omitted_batch(self):
        plan, reports = self.make()
        with self.assertRaisesRegex(ValueError, "mismatched"):
            consume_batches(plan, reports[:-1])

    def test_rejects_incomplete_report(self):
        plan, reports = self.make()
        reports[0]["checks"].clear()
        reports[0]["checkedCount"] = 0
        reports[0]["audioEvidenceCount"] = 0
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            consume_batches(plan, reports)

    def test_rejects_wrong_day_and_technical_approval_claims(self):
        plan, reports = self.make()
        reports[0]["observationDate"] = "2026-11-21"
        with self.assertRaisesRegex(ValueError, "untrusted"):
            consume_batches(plan, reports)
        plan, reports = self.make()
        reports[0]["technicalVerifiedCount"] = 1
        with self.assertRaisesRegex(ValueError, "untrusted"):
            consume_batches(plan, reports)

    def test_rejects_report_with_raw_url(self):
        plan, reports = self.make()
        reports[0]["checks"][0]["streamUrl"] = URL1
        with self.assertRaisesRegex(ValueError, "raw URLs"):
            consume_batches(plan, reports)

    def test_rejects_forged_audio_count(self):
        plan, reports = self.make()
        reports[0]["audioEvidenceCount"] = 99
        with self.assertRaisesRegex(ValueError, "audio sample count"):
            consume_batches(plan, reports)

    def test_rejects_duplicate_scheduled_uuid(self):
        plan, reports = self.make()
        plan["batches"][1]["candidates"][0]["stationuuid"] = plan["batches"][0]["candidates"][0]["stationuuid"]
        with self.assertRaisesRegex(ValueError, "more than once"):
            consume_batches(plan, reports)

    def test_rejects_reordered_or_oversized_batches(self):
        plan, reports = self.make()
        plan["batches"][0]["batchNumber"] = 2
        with self.assertRaisesRegex(ValueError, "batch number"):
            consume_batches(plan, reports)
        plan, reports = self.make()
        plan["safety"]["maxProbesPerDay"] = 41
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            consume_batches(plan, reports)

    def test_legacy_history_can_migrate_in_integrated_bridge(self):
        from radio_stream_recheck_ledger import next_evidence_report
        plan, reports = self.make()
        legacy = next_evidence_report(reports[0])
        result = consume_batches(plan, reports, legacy)
        self.assertEqual(result["streamEvidence"]["streamHistoryMode"], "per_stream")

    def test_empty_batch_does_not_fabricate_proof(self):
        plan = plan_batches(catalog(), discovery(), day="2026-11-20")
        report = consume_batches(plan, [])
        self.assertEqual(report["processedChecks"], 0)
        self.assertEqual(report["streamEvidence"]["records"], [])
        self.assertFalse(report["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
