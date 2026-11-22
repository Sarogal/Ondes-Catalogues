"""Offline security and pagination tests for national OpenAgenda index discovery."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_public_agenda_index import (
    API, PAGE_SIZE, SCHEMA, STATE_SCHEMA, _validated_page,
    load_state, read_index_page, scan_index_pages,
    _write_new_report, _write_state_atomic, main,
)

KEY = "oa_pk_example_read_only_key_long_enough"


def row(uid, name=None, **extra):
    return {
        "uid": uid, "slug": f"agenda-{uid}",
        "title": name or f"Agenda de test {uid}",
        **extra,
    }


def page(uids, after=None):
    return {"agendas": [row(uid) for uid in uids], "after": after}


class Response:
    def __init__(self, request, document, *, status=200, redirect=None):
        self.status = status
        self.url = redirect or request.full_url
        self.raw = io.BytesIO(json.dumps(document).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        return self.raw.read(size)


class NationalOpenAgendaIndexTests(unittest.TestCase):
    def test_documented_api_get_uses_private_key_header_and_after_array(self):
        request_urls = []
        def fetch(request, timeout):
            self.assertEqual(timeout, 20)
            self.assertTrue(request.has_header("Key"))
            self.assertEqual(request.get_header("Key"), KEY)
            self.assertNotIn(KEY, request.full_url)
            request_urls.append(request.full_url)
            return Response(request, page([102, 103], after=[1, 103]))
        got = read_index_page(KEY, [1, 101], size=2, opener=fetch)
        self.assertEqual(got["after"], [1, 103])
        self.assertEqual([x["uid"] for x in got["agendas"]], [102, 103])
        self.assertEqual(request_urls, [API + "?size=2&after%5B%5D=1&after%5B%5D=101"])

    def test_public_api_index_does_not_depend_on_venue_or_genre_whitelist(self):
        asked = []
        def fetch(key, cursor, *, size):
            asked.append((cursor, size))
            if cursor is None:
                return page([1, 2, 3], after=[1, 3])
            return page([4, 5])
        result = scan_index_pages([2, 5], reader=fetch, pages=4)
        self.assertEqual(result["counts"]["pages_read"], 2)
        self.assertEqual(result["counts"]["configured_agenda_seen"], 2)
        self.assertEqual(result["counts"]["new_index_agendas_unverified"], 3)
        self.assertEqual([x["agenda_uid"] for x in result["new_agenda_candidates"]],
                         [1, 3, 4])
        self.assertTrue(result["index_pass_exhausted"])
        self.assertIsNone(result["next_cursor"])
        self.assertEqual(asked, [(None, PAGE_SIZE), ([1, 3], PAGE_SIZE)])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["owner_independently_verified"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)

    def test_pagination_can_resume_without_reusing_previous_page(self):
        def first(key, cursor, *, size):
            self.assertIsNone(cursor)
            return page([1, 2], after=[1, 2])
        one = scan_index_pages([], pages=1, reader=first)
        self.assertFalse(one["index_pass_exhausted"])
        self.assertEqual(one["next_cursor"], [1, 2])
        def later(key, cursor, *, size):
            self.assertEqual(cursor, [1, 2])
            return page([3])
        two = scan_index_pages([], pages=1, reader=later,
                               start_cursor=one["next_cursor"])
        self.assertTrue(two["index_pass_exhausted"])
        self.assertEqual([r["agenda_uid"] for r in two["new_agenda_candidates"]], [3])

    def test_api_self_declared_official_flag_never_certifies_source(self):
        result = scan_index_pages([], pages=1,
                                  reader=lambda key, cursor, size:
                                  {"agendas": [row(1, official=True)],
                                   "after": None})
        item = result["new_agenda_candidates"][0]
        self.assertFalse(item["owner_verified"])
        self.assertFalse(item["organiser_verified"])
        self.assertFalse(item["rights_reviewed"])
        self.assertFalse(item["publisher_enabled"])

    def test_invalid_page_and_stale_or_repeat_cursor_fail_closed(self):
        cases = (
            {"agendas": None, "after": None},
            page([1, 1]),
            page([1], after=[1, 99]),  # cursor itself is valid
            page([], after=[1, 9]),
            page([1], after=[1, 3]),
            {"agendas": [row(True)], "after": None},
            {"agendas": [row(1, name="x" * 501)], "after": None},
            {"agendas": [{**row(1), "slug": "INVALID"}], "after": None},
            {"agendas": [{**row(1), "title": ""}], "after": None},
        )
        for x in cases:
            with self.subTest(payload=x):
                # Valid cursor case requires a separate check, not rejection.
                if x.get("after") in ([1, 99], [1, 3]) and x.get("agendas"):
                    rows, after = _validated_page(x, PAGE_SIZE, None)
                    self.assertEqual(len(rows), 1)
                    continue
                with self.assertRaises(ValueError):
                    _validated_page(x, PAGE_SIZE, None)
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_cursor"):
            _validated_page(page([1], after=[1, 2]), PAGE_SIZE, [1, 2])
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_cursor_reuse"):
            state = iter([
                page([1], after=[1, 2]),
                page([2], after=[1, 3]),
                page([3], after=[1, 2]),
            ])
            scan_index_pages([], pages=3, reader=lambda *args, **kwargs: next(state))
        with self.assertRaisesRegex(ValueError, "repeated_oa_agenda"):
            it = iter([page([1], [1, 1]), page([1])])
            scan_index_pages([], pages=2,
                             reader=lambda *args, **kwargs: next(it))

    def test_network_redirection_status_and_bad_key_are_refused(self):
        def fetch_redirect(req, timeout):
            return Response(req, page([1]), redirect="https://fake.invalid")
        with self.assertRaisesRegex(ValueError, "unexpected_oa_index_endpoint"):
            read_index_page(KEY, opener=fetch_redirect)
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_request"):
            read_index_page("oa_sk_admin_key_rejected")
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_request"):
            read_index_page(KEY, after=[True, 10])
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_request"):
            read_index_page(KEY, size=101)

    def test_private_cursor_and_report_are_safe_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / "cursor.json"
            out = root / "unique_report.json"
            self.assertEqual(load_state(state_path)["completed_passes"], 0)
            _write_new_report(out, {"schema": SCHEMA, "public_writes": 0})
            with self.assertRaisesRegex(ValueError, "private_report_must_be_new"):
                _write_new_report(out, {})
            _write_state_atomic(state_path, {
                "schema": STATE_SCHEMA, "after": [1, 42],
                "completed_passes": 0,
            })
            self.assertEqual(load_state(state_path)["after"], [1, 42])
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            bad = root / "dangling"
            bad.symlink_to(root / "missing")
            with self.assertRaisesRegex(ValueError, "private_state_symlink"):
                load_state(bad)

    def test_bad_read_configs_are_rejected_without_network(self):
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_scan"):
            scan_index_pages([True], reader=lambda *a, **k: None)
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_scan"):
            scan_index_pages([], pages=100, reader=lambda *a, **k: None)
        with self.assertRaisesRegex(ValueError, "invalid_oa_index_scan"):
            scan_index_pages([10, 10], reader=lambda *a, **k: None)

    def test_default_command_is_dry_run_and_produces_no_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cfg = root / "sources.json"
            cfg.write_text(json.dumps({
                "schema": "ptitesondes.sources.v1",
                "openagenda_agendas": [111, 222]}), encoding="utf-8")
            state, report = root / "state.json", root / "result.json"
            args = ["cmd", "--private-source-config", str(cfg),
                    "--private-cursor-state", str(state),
                    "--output-private-report", str(report)]
            with patch.object(sys, "argv", args):
                with patch.dict(os.environ, {"OPENAGENDA_READ_KEY": ""}):
                    main()
            self.assertFalse(state.exists())
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
