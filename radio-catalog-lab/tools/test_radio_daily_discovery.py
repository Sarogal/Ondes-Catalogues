"""Synthetic/no-network checks for the bounded daily Radio Browser discovery."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from radio_daily_discovery import (
    candidate, discover, genre_evidence, is_public_stream, known_uuids,
    normalize, page_offsets, fetch_page,
)

ID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ID_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def station(uid=ID_A, name="New Metal Radio", tags="heavy metal",
            url="https://stream.example.org/live.mp3", last_ok=True):
    return {
        "stationuuid": uid, "name": name, "tags": tags,
        "url_resolved": url, "lastcheckok": last_ok,
        "countrycode": "FR", "favicon": "https://img.example.org/logo.png",
        "homepage": "https://radio.example.org/",
    }


class DailyDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.day = dt.date(2026, 11, 20)

    def scan(self, pages, known=None, tags=None, names=None, max_pages=2):
        calls = []
        def fetch(field, term, offset, limit):
            calls.append((field, term, offset, limit))
            return pages.get((field, term, offset), [])
        report = discover(
            fetch=fetch, tags=tags if tags is not None else ["metal"],
            names=names if names is not None else [],
            day=self.day, page_size=2, max_pages=max_pages,
            known_ids=known or set(),
        )
        return report, calls

    def test_brand_new_uuid_not_in_whitelist_is_candidate(self):
        report, calls = self.scan({("tag", "metal", 0): [station()]})
        self.assertEqual(report["unrecognizedCandidateCount"], 1)
        self.assertEqual(report["candidates"][0]["stationuuid"], ID_A)
        self.assertEqual(report["candidates"][0]["status"], "candidate_requires_qualification")
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["qualifiedStreamCount"], 0)

    def test_known_ids_are_not_deletion_or_new_candidate(self):
        report, _ = self.scan({("tag", "metal", 0): [station()]}, {ID_A})
        self.assertEqual(report["observedUniqueUuidCount"], 1)
        self.assertEqual(report["unrecognizedCandidateCount"], 0)

    def test_missing_from_today_does_not_remove_known_station(self):
        report, _ = self.scan({}, {ID_A, ID_B})
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["knownUuidInputCount"], 2)
        self.assertFalse(report["publicationAllowed"])

    def test_name_search_can_find_station_with_no_genre_tags(self):
        report, calls = self.scan(
            {("name", "punk", 0): [station(ID_B, name="Punk Movement FM", tags="")]},
            tags=[], names=["punk"])
        self.assertEqual(report["candidates"][0]["stationuuid"], ID_B)
        self.assertIn(("name", "punk", 0, 2), calls)

    def test_reject_irrelevant_pop_without_genre_marker(self):
        report, _ = self.scan({("tag", "metal", 0): [
            station(ID_B, name="Pop Hits", tags="dance,jazz")]})
        self.assertEqual(report["candidates"], [])

    def test_lastcheck_fail_is_not_automatically_admitted(self):
        report, _ = self.scan({("tag", "metal", 0): [
            station(last_ok=False)]})
        self.assertEqual(report["candidates"][0]["status"], "needs_stream_check")

    def test_private_and_local_addresses_cannot_become_streams(self):
        bad = (
            "http://127.0.0.1/live", "http://192.168.1.8/rock",
            "https://localhost/a", "https://foo.local/a",
            "file:///tmp/live", "https://user:pass@example.org/a",
            "https://example.org/a#fragment", "http://169.254.0.1/a",
            "http://[::1]:8000/a",
        )
        for value in bad:
            with self.subTest(value=value):
                self.assertFalse(is_public_stream(value))
                row = candidate(station(url=value), set())
                self.assertIsNotNone(row)
                self.assertIsNone(row["streamUrl"])
                self.assertEqual(row["status"], "needs_stream_check")
        self.assertTrue(is_public_stream("https://radio.example.org:8443/live"))

    def test_bad_uuid_and_missing_names_are_discarded(self):
        self.assertIsNone(candidate(station("not-uuid"), set()))
        self.assertIsNone(candidate(station(name=""), set()))

    def test_duplicate_name_is_review_only_without_auto_merge(self):
        report, _ = self.scan({("tag", "metal", 0): [
            station(ID_A), station(ID_B)]})
        self.assertEqual(report["observedUniqueUuidCount"], 2)
        self.assertTrue(all(r["duplicateIdentityRisk"] for r in report["candidates"]))
        self.assertTrue(all(r["status"] == "needs_duplicate_review"
                            for r in report["candidates"]))
        self.assertEqual({r["stationuuid"] for r in report["candidates"]}, {ID_A, ID_B})

    def test_duplicate_stream_with_different_names_requires_review(self):
        report, _ = self.scan({("tag", "metal", 0): [
            station(ID_A, name="Metal One"), station(ID_B, name="Metal Two")]})
        self.assertEqual({r["status"] for r in report["candidates"]},
                         {"needs_duplicate_review"})

    def test_same_station_found_by_multiple_queries_is_deduped_by_uuid(self):
        report, _ = self.scan({
            ("tag", "metal", 0): [station(ID_A)],
            ("name", "metal", 0): [station(ID_A)],
        }, tags=["metal"], names=["metal"])
        self.assertEqual(report["observedUniqueUuidCount"], 1)
        self.assertEqual(len(report["candidates"]), 1)

    def test_scan_queries_are_not_hardcoded_station_ids(self):
        report, calls = self.scan({("tag", "metal", 0): [
            station(ID_C, name="Metal Underground")]})
        self.assertEqual([c[1] for c in calls], ["metal"])
        self.assertEqual(report["candidates"][0]["stationuuid"], ID_C)

    def test_deeper_window_rotates_by_day_and_covers_latest(self):
        a = page_offsets(self.day, 100, 3)
        b = page_offsets(self.day + dt.timedelta(days=1), 100, 3)
        self.assertEqual(a[0], 0)
        self.assertEqual(b[0], 0)
        self.assertNotEqual(a[1:], b[1:])
        self.assertEqual(len(a), 3)

    def test_budget_caps_and_invalid_query_list_fail(self):
        with self.assertRaises(ValueError):
            page_offsets(self.day, 100, 21)
        with self.assertRaises(ValueError):
            page_offsets(self.day, 0, 2)
        with self.assertRaises(ValueError):
            self.scan({}, tags=[], names=[])
        with self.assertRaises(ValueError):
            self.scan({}, tags=["x"] * 41, names=[])

    def test_network_failure_is_not_an_empty_success_report(self):
        def broken(field, term, offset, limit):
            raise RuntimeError("backend unavailable")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            discover(fetch=broken, tags=["metal"], names=[],
                     day=self.day, page_size=100, max_pages=2,
                     known_ids=set())

    def test_known_uuid_baseline_is_dynamic_and_validated(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "approved-ids.json"
            path.write_text(json.dumps({"known_station_uuids": [ID_A]}))
            self.assertEqual(known_uuids(path), {ID_A})
            path.write_text('["invalid-id"]')
            with self.assertRaises(ValueError):
                known_uuids(path)

    def test_fingerprint_not_a_fake_exact_identity(self):
        self.assertEqual(normalize("MÖTÖRHEAD"), "motorhead")
        self.assertEqual(genre_evidence("Metalcore Zone", "metal"),
                         ["metal"])
        self.assertIn("hard rock", genre_evidence("Pure Hard Rock", ""))

    def test_bad_api_host_not_followed(self):
        with self.assertRaises(RuntimeError):
            fetch_page(["attacker.example"], "tag", "metal", 0, 2)


if __name__ == "__main__":
    unittest.main()
