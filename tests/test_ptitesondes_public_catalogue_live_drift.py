"""Offline adversarial test of the exact GitHub Pages public JSON drift reader."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_public_catalogue_live_drift import (
    LIVE_URL, LOCAL_PATH, MAX_BYTES, SCHEMA, check_served_catalogue,
)
from ptitesondes_nonmusical_catalogue_shape_dryrun import _hash

DOC = json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
STAMP = datetime.fromisoformat(DOC["updated_at"])
RECENT = STAMP + timedelta(hours=2)


class Reply:
    status = 200
    headers = {"Content-Type": "application/json; charset=utf-8"}

    def __init__(self, req, raw, *, target=None, status=200, mime=None):
        self.req = req
        self.body = raw
        self.status = status
        self.target = req.full_url if target is None else target
        self.headers = {"Content-Type": mime or "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.target

    def read(self, n):
        return self.body[:n]


class Reader:
    def __init__(self, doc=None, **kwargs):
        self.raw = json.dumps(DOC if doc is None else doc).encode("utf-8")
        self.kwargs = kwargs
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append((req.full_url, req.get_method(), timeout))
        return Reply(req, self.raw, **self.kwargs)


class PublicLiveCatalogueDriftTests(unittest.TestCase):
    def safe(self, r):
        self.assertEqual(r["schema"], SCHEMA)
        self.assertFalse(r["catalogue_event_fields_in_output"])
        self.assertFalse(r["publisher_connected"])
        self.assertFalse(r["rights_reviewed"])
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(r["public_writes"], 0)
        self.assertTrue(r["data_age_is_not_workflow_run_proof"])
        self.assertTrue(r["live_fetch_does_not_grant_publisher_permission"])
        for bad in ("events", "additions", "source_url", "city",
                    "age_min", "venue", "mpt.montpellier.fr"):
            self.assertNotIn(bad, r)
        self.assertNotIn("Toulouse", json.dumps(r))
        self.assertNotIn("Montpellier", json.dumps(r))

    def test_exact_public_url_and_same_repo_data_is_reassuring_not_approval(self):
        reader = Reader()
        r = check_served_catalogue(RECENT, reader=reader)
        self.assertEqual(r["stage"], "matching_live_catalogue_recent_data_change")
        self.assertEqual(reader.calls, [(LIVE_URL, "GET", 20)])
        self.assertTrue(r["same_data_as_checked_out_repository"])
        self.assertTrue(r["data_last_changed_within_24h"])
        self.assertEqual(r["live_event_count"], len(DOC["events"]))
        self.assertEqual(r["local_event_count"], len(DOC["events"]))
        self.assertEqual(r["live_data_timestamp"], STAMP.isoformat())
        self.safe(r)

    def test_old_content_timestamp_is_not_workflow_health_proof(self):
        r = check_served_catalogue(
            STAMP + timedelta(days=4), reader=Reader())
        self.assertEqual(r["stage"],
                         "matching_data_last_updated_over_24h_ago")
        self.assertTrue(r["same_data_as_checked_out_repository"])
        self.assertFalse(r["data_last_changed_within_24h"])
        self.safe(r)

    def test_future_date_is_not_fresh(self):
        r = check_served_catalogue(STAMP - timedelta(days=1), reader=Reader())
        self.assertFalse(r["data_last_changed_within_24h"])
        self.safe(r)

    def test_even_one_content_difference_is_reported_as_live_drift(self):
        different = deepcopy(DOC)
        different["events"][0]["title"] = "An alternative changed title"
        r = check_served_catalogue(RECENT, reader=Reader(different))
        self.assertEqual(r["stage"],
                         "live_catalogue_differs_from_repository")
        self.assertFalse(r["same_data_as_checked_out_repository"])
        self.assertEqual(r["live_event_count"], len(DOC["events"]))
        self.safe(r)

    def test_live_updated_at_only_difference_also_is_drift(self):
        different = deepcopy(DOC)
        different["updated_at"] = (
            STAMP + timedelta(minutes=2)).isoformat()
        r = check_served_catalogue(RECENT, reader=Reader(different))
        self.assertFalse(r["same_data_as_checked_out_repository"])
        self.safe(r)

    def test_redirect_status_bad_type_and_oversized_are_not_facts(self):
        cases = [
            Reader(target="https://evil.example/stolen"),
            Reader(target=LIVE_URL + "?p=1"),
            Reader(status=503),
            Reader(mime="text/html"),
        ]
        over = Reader()
        over.raw = b" " * (MAX_BYTES + 1)
        cases.append(over)
        for reader in cases:
            with self.subTest(kwargs=reader.kwargs):
                r = check_served_catalogue(RECENT, reader=reader)
                self.assertEqual(r["stage"],
                                 "live_catalogue_unavailable_or_invalid")
                self.assertEqual(r["live_event_count"], 0)
                self.safe(r)

    def test_timeout_and_reader_exception_fail_closed_without_raw_error(self):
        def offline(*_args, **_kwargs):
            raise TimeoutError("private event / secret query exception")
        r = check_served_catalogue(RECENT, reader=offline)
        self.assertEqual(r["stage"],
                         "live_catalogue_unavailable_or_invalid")
        self.assertNotIn("secret", json.dumps(r))
        self.safe(r)

    def test_corrupted_json_naive_time_and_duplicate_ids_are_rejected(self):
        cases = [
            b"{broken",
            b"[]",
            json.dumps(dict(DOC, updated_at="2026-11-20")).encode(),
            json.dumps(dict(DOC, updated_at="not-a-date")).encode(),
            json.dumps(dict(DOC, version=999)).encode(),
            b'{"version":3,"events":[NaN],"updated_at":"2026-11-20T00:00:00+01:00"}',
        ]
        dup = deepcopy(DOC)
        dup["events"][1]["id"] = dup["events"][0]["id"]
        cases.append(json.dumps(dup).encode("utf-8"))
        for body in cases:
            with self.subTest(size=len(body)):
                reader = Reader()
                reader.raw = body
                r = check_served_catalogue(RECENT, reader=reader)
                self.assertEqual(r["stage"],
                                 "live_catalogue_unavailable_or_invalid")
                self.safe(r)

    def test_corrupted_checked_out_reference_fails_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "sorties.json"
            local.write_text("{ invalid json", encoding="utf-8")
            reader = Reader()
            r = check_served_catalogue(RECENT, reader=reader, local_file=local)
            self.assertEqual(r["stage"], "checked_out_reference_invalid")
            self.assertFalse(reader.calls)
            self.safe(r)

    def test_invalid_clock_returns_without_network(self):
        reader = Reader()
        for instant in (None, "2026-11-20", datetime(2026, 11, 20)):
            r = check_served_catalogue(instant, reader=reader)
            self.assertEqual(r["stage"], "invalid_clock")
            self.safe(r)
        self.assertFalse(reader.calls)

    def test_repo_file_is_read_only_during_comparison(self):
        before = LOCAL_PATH.read_bytes()
        r = check_served_catalogue(RECENT, reader=Reader())
        self.assertEqual(LOCAL_PATH.read_bytes(), before)
        self.assertEqual(_hash(DOC), _hash(json.loads(before)))
        self.safe(r)


if __name__ == "__main__":
    unittest.main()
