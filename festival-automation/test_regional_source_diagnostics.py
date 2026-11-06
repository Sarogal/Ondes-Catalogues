"""Regression tests for private, review-only regional scan diagnostics."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from official_watch import permitted_url
from regional_festival_discovery import APPROVED, scan_regional_indexes
from regional_source_diagnostics import (
    KEY, MAX_RECORDS, record_regional_diagnostics,
)

BASE = "https://sortir.limoges.fr/agenda"
ROCK = BASE + "?keys=rock"
PAGE = ROCK + "&page=1"
DAY = "2026-11-06"
REGION = "Nouvelle-Aquitaine"


def observation(origin=BASE, url=BASE, status="SCANNED",
                anchors=7, links=0, script=False):
    return {
        "index_url": origin, "checked_url": url, "region": REGION,
        "status": status, "visible_anchors": anchors,
        "thematic_links": links, "script_backed_linkless_hint": script,
    }


class RegionalSourceDiagnosticsTests(unittest.TestCase):
    def test_successful_non_candidate_scan_is_recorded_privately(self):
        state = {}
        self.assertEqual(record_regional_diagnostics(
            state, [observation()], APPROVED, DAY, permitted_url), 1)
        saved = state[KEY][BASE]
        self.assertEqual(saved["page_diagnostic"],
                         "VISIBLE_LINKS_NO_CANDIDATE")
        self.assertEqual(saved["visible_anchors"], 7)
        self.assertEqual(saved["thematic_links"], 0)
        self.assertEqual(saved["lastSuccessful"], DAY)
        self.assertFalse(saved["publication_authorized"])
        self.assertNotIn("html", saved)
        self.assertNotIn("candidate_url", saved)

    def test_failure_after_success_preserves_success_date_not_success_status(self):
        state = {}
        record_regional_diagnostics(state, [observation()],
                                    APPROVED, DAY, permitted_url)
        record_regional_diagnostics(
            state, [observation(status="INACCESSIBLE")], APPROVED,
            "2026-11-07", permitted_url)
        saved = state[KEY][BASE]
        self.assertEqual(saved["lastSuccessful"], DAY)
        self.assertEqual(saved["lastAttempted"], "2026-11-07")
        self.assertEqual(saved["page_diagnostic"], "FETCH_FAILED")
        self.assertEqual(saved["status"], "INACCESSIBLE")
        self.assertEqual(saved["visible_anchors"], 0)

    def test_pagination_records_are_approved_and_not_fetchable(self):
        state = {}
        record_regional_diagnostics(
            state, [observation(ROCK, PAGE, anchors=0, script=True)],
            APPROVED, DAY, permitted_url)
        saved = state[KEY][PAGE]
        self.assertEqual(saved["page_kind"], "PAGINATION")
        self.assertEqual(saved["source_index"], ROCK)
        self.assertEqual(saved["page_diagnostic"], "NO_VISIBLE_LINKS")
        self.assertTrue(saved["possible_dynamic"])
        self.assertFalse(saved["publication_authorized"])
        self.assertNotIn("fetch_eligible", saved)

    def test_hostile_prior_state_cannot_inject_urls_or_approvals(self):
        state = {KEY: {
            "https://127.0.0.1/admin": {
                "source_index": BASE, "checked_url": "https://127.0.0.1/admin",
                "publication_authorized": False, "status": "SCANNED",
                "lastAttempted": DAY},
            BASE: {
                "source_index": BASE, "checked_url": BASE,
                "region": REGION, "page_kind": "ROOT",
                "publication_authorized": True, "status": "SCANNED",
                "lastAttempted": DAY, "lastSuccessful": DAY,
                "page_diagnostic": "CANDIDATE_LINKS_REVIEW_ONLY"},
        }}
        record_regional_diagnostics(
            state, [observation()], APPROVED, DAY, permitted_url)
        self.assertEqual(list(state[KEY]), [BASE])
        self.assertFalse(state[KEY][BASE]["publication_authorized"])

    def test_integration_preserves_diagnostics_without_publication(self):
        state = {}
        r = {"schema": "grossesondes.source-watch-report.v1",
             "date": DAY}
        visits = []
        def fetch(url):
            visits.append(url)
            return "<main><a href='/agenda/spectacle'>Spectacle 2027</a></main>"
        result = scan_regional_indexes(
            r, state, [{"id": "na-limoges", "url": BASE,
                        "region": REGION}], DAY, fetch=fetch, limit=1)
        self.assertEqual(result, [])
        self.assertEqual(visits, [BASE])
        self.assertEqual(state[KEY][BASE]["status"], "SCANNED")
        self.assertEqual(state[KEY][BASE]["page_diagnostic"],
                         "VISIBLE_LINKS_NO_CANDIDATE")
        self.assertEqual(r["regional_festival_publications"], 0)

    def test_private_history_is_bounded_and_old_rows_expire(self):
        state = {}
        record_regional_diagnostics(state, [observation()], APPROVED,
                                    DAY, permitted_url)
        record_regional_diagnostics(state, [], APPROVED,
                                    "2027-01-20", permitted_url)
        self.assertEqual(state[KEY], {})
        self.assertLessEqual(len(state[KEY]), MAX_RECORDS)


if __name__ == "__main__":
    unittest.main()
