"""Synthetic offline tests of daily stream batches and scratch-only URL handling."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from radio_catalog_probe_batch_plan import (
    plan_batches, write_temporary_probe_inputs,
)


def uid(n: int) -> str:
    return str(uuid.UUID(int=n + 1))


def historical(n: int, *, codec="MP3", suffix="mp3"):
    ident = uid(n)
    return {
        "go_station_id": f"go-station-{n:06d}",
        "display_name": f"Radio {n}",
        "country_code": "FR",
        "legacy_aliases": [ident],
        "radio_browser_uuids": [{"uuid": ident}],
        "streams": [{"stream_id": "primary",
                     "url": f"https://radio.example.org/{n}.{suffix}",
                     "codec": codec, "state": "candidate"}],
    }


def catalog(*stations):
    return {"schema_version": 1, "stations": list(stations), "tombstones": []}


def discovery(*candidates):
    return {
        "schemaVersion": 1, "scanDate": "2026-11-20",
        "publicationAllowed": False, "candidates": list(candidates),
    }


def candidate(n: int, *, suffix="aac", status="candidate_requires_qualification"):
    return {
        "stationuuid": uid(n), "name": f"New Metal {n}",
        "countrycode": "FR", "status": status,
        "streamUrl": f"https://radio.example.org/new-{n}.{suffix}",
        "codec": "AAC",
    }


class BatchPlanTests(unittest.TestCase):
    def test_339_historical_and_10_discovery_are_bounded_and_fair(self):
        old = catalog(*(historical(i) for i in range(339)))
        fresh = discovery(*(candidate(i) for i in range(500, 510)))
        plan = plan_batches(old, fresh, day="2026-11-20")
        self.assertEqual(plan["historicalStreamCount"], 339)
        self.assertEqual(plan["plannedProbeCount"], 40)
        self.assertEqual(plan["plannedHistoricalCount"], 32)
        self.assertEqual(plan["plannedDiscoveryCount"], 8)
        self.assertEqual(len(plan["batches"]), 8)
        self.assertTrue(all(b["candidateCount"] <= 5 for b in plan["batches"]))
        all_ids = [r["stationuuid"] for b in plan["batches"] for r in b["candidates"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertEqual(plan["safety"]["oldStationsDeleted"], 0)

    def test_historical_339_can_all_receive_first_turn_over_11_days(self):
        old = catalog(*(historical(i) for i in range(339)))
        fresh = discovery(*(candidate(i) for i in range(500, 510)))
        inspected = set()
        for i in range(11):
            date = (dt.date(2026, 11, 20) + dt.timedelta(days=i)).isoformat()
            report = plan_batches(old, fresh, day=date)
            inspected.update(row["stationuuid"] for b in report["batches"]
                             for row in b["candidates"] if row["source"] == "historical")
        self.assertEqual(len(inspected), 339)

    def test_no_discovery_uses_all_spare_capacity_for_historical(self):
        report = plan_batches(
            catalog(*(historical(i) for i in range(100))), discovery(),
            day="2026-11-20")
        self.assertEqual(report["plannedHistoricalCount"], 40)
        self.assertEqual(report["plannedDiscoveryCount"], 0)

    def test_new_candidates_do_not_starve_with_large_legacy_backlog(self):
        report = plan_batches(
            catalog(*(historical(i) for i in range(100))),
            discovery(*(candidate(i) for i in range(500, 505))),
            day="2026-11-20")
        self.assertEqual(report["plannedDiscoveryCount"], 5)
        self.assertEqual(report["plannedHistoricalCount"], 35)

    def test_hls_and_unknown_queued_but_not_in_first_probe_batch(self):
        old = catalog(
            historical(1, codec="AAC", suffix="m3u8"),
            historical(2, codec="FLAC", suffix="flac"),
            historical(3),
        )
        report = plan_batches(old, discovery(), day="2026-11-20")
        self.assertEqual(report["separateHlsCount"], 1)
        self.assertEqual(report["unaddressedFormatCount"], 1)
        self.assertEqual(report["plannedProbeCount"], 1)
        self.assertEqual(report["batches"][0]["candidates"][0]["stationuuid"], uid(3))

    def test_same_uuid_multiple_stream_variants_at_most_one_probe_today(self):
        original = historical(1)
        original["streams"].append({
            "stream_id": "backup",
            "codec": "AAC", "url": "https://radio.example.org/backup.aac"})
        report = plan_batches(catalog(original), discovery(), day="2026-11-20")
        self.assertEqual(report["historicalStreamCount"], 2)
        self.assertEqual(report["plannedProbeCount"], 1)

    def test_deduplicate_between_historical_and_directory_today(self):
        report = plan_batches(catalog(historical(1)), discovery(candidate(1)),
                              day="2026-11-20")
        self.assertEqual(report["plannedProbeCount"], 1)

    def test_no_raw_stream_urls_in_scheduling_report(self):
        result = plan_batches(catalog(historical(1)), discovery(candidate(3)),
                              day="2026-11-20")
        text = json.dumps(result)
        self.assertNotIn("https://", text)
        self.assertNotIn("radio.example.org", text)
        self.assertIn("streamSha256", text)
        self.assertNotIn("streamUrl", text)

    def test_hard_budget_rejection(self):
        for kwargs in ({"max_daily": 41}, {"max_daily": 0},
                       {"max_per_batch": 6}, {"max_per_batch": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                plan_batches(catalog(historical(1)), discovery(),
                             day="2026-11-20", **kwargs)

    def test_scratch_inputs_outside_checkout_only_and_unique_per_batch(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            checkout = parent / "repo"
            checkout.mkdir()
            outside = parent / "scratch"
            plan = plan_batches(catalog(historical(1)), discovery(candidate(2)),
                                day="2026-11-20")
            with self.assertRaises(ValueError):
                write_temporary_probe_inputs(
                    plan, catalog(historical(1)), discovery(candidate(2)),
                    checkout / "probe", workspace=checkout)
            self.assertFalse((checkout / "probe").exists())
            write_temporary_probe_inputs(plan, catalog(historical(1)),
                                         discovery(candidate(2)), outside,
                                         workspace=checkout)
            files = sorted(outside.glob("*.json"))
            self.assertEqual(len(files), 1)
            payload = json.loads(files[0].read_text())
            self.assertEqual(len(payload["candidates"]), 2)
            self.assertEqual(len({c["stationuuid"] for c in payload["candidates"]}), 2)
            self.assertFalse(payload["publicationAllowed"])
            self.assertIn("streamUrl", payload["candidates"][0])
            with self.assertRaises(ValueError):
                write_temporary_probe_inputs(
                    plan, catalog(historical(1)), discovery(candidate(2)),
                    outside, workspace=checkout)

    def test_stale_forged_stream_hash_refuses_all_scratch_writes(self):
        with tempfile.TemporaryDirectory() as root:
            parent = Path(root)
            workspace = parent / "repo"
            workspace.mkdir()
            plan = plan_batches(catalog(historical(1)), discovery(),
                                day="2026-11-20")
            plan["batches"][0]["candidates"][0]["streamSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "Stale or forged"):
                write_temporary_probe_inputs(plan, catalog(historical(1)),
                                             discovery(), parent / "scratch",
                                             workspace=workspace)
            self.assertFalse((parent / "scratch").exists())

    def test_empty_catalog_without_central_data_is_allowed_only_as_empty_queue(self):
        report = plan_batches(catalog(), discovery(candidate(4)),
                              day="2026-11-20")
        self.assertEqual(report["plannedProbeCount"], 1)
        self.assertEqual(report["historicalStreamCount"], 0)


if __name__ == "__main__":
    unittest.main()
