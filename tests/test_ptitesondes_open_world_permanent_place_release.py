from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch
from test_ptitesondes_open_world_permanent_place_draft import ADMIN
from test_ptitesondes_open_world_permanent_place_evidence import CITY, VENUE, ZIP, URL, HTML, OSM
from ptitesondes_open_world_permanent_place_draft import build_draft
from ptitesondes_place_preflight import merge_open_world_drafts, live_review
from ptitesondes_open_world_permanent_place_publisher_preview import review_drafts
from test_ptitesondes_open_world_permanent_place_publisher_preview import state

DAY = date(2026, 11, 26)
EMPTY = {"version": 1, "updated_at": DAY.isoformat(), "places": []}


def fresh():
    return build_draft(CITY, VENUE, ZIP, URL, HTML, OSM, ADMIN, DAY)


class OpenWorldPlaceReleaseTests(unittest.TestCase):
    def test_independently_built_candidate_appended_once(self):
        p = fresh()
        out, counts = merge_open_world_drafts(EMPTY, [p, p], DAY)
        self.assertEqual(out["places"], [p])
        self.assertEqual(counts["open_world_added"], 1)
        self.assertEqual(counts["open_world_duplicate"], 1)
        self.assertEqual(EMPTY["places"], [])
        again, counts = merge_open_world_drafts(out, [p], DAY)
        self.assertIs(again, out)
        self.assertEqual(counts["open_world_added"], 0)

    def test_legacy_place_preserved_and_alias_rejected(self):
        original = dict(fresh(), id="legacy-reviewed-place")
        current = dict(EMPTY, places=[original])
        snapshot = deepcopy(current)
        out, counts = merge_open_world_drafts(current, [fresh()], DAY)
        self.assertEqual(out, snapshot)
        self.assertEqual(current, snapshot)
        self.assertEqual(counts["open_world_duplicate"], 1)

    def test_invalid_or_stale_draft_never_blocks_valid_other(self):
        p = fresh()
        stale = dict(p, reviewed_at="2026-11-25")
        invalid = dict(p, geo_source_url="https://www.openstreetmap.org/node/999")
        out, counts = merge_open_world_drafts(EMPTY, [stale, invalid, p], DAY)
        self.assertEqual(out["places"], [p])
        self.assertEqual(counts["open_world_invalid"], 2)

    def test_fresh_sources_build_candidate_not_private_coordinates(self):
        with patch("ptitesondes_open_world_permanent_place_publisher_preview.approved_municipal_page_host",
                   return_value="venue.example"):
            drafts, summary = review_drafts(state(), DAY,
                osm_fetch=lambda *_: OSM, page_read=lambda _: HTML,
                directory_fetch=lambda _: {}, admin_fetch=lambda *_: ADMIN)
        self.assertEqual(drafts, [fresh()])
        self.assertEqual(summary["complete_draft_records"], 1)

    def test_negative_children_claim_does_not_become_activity(self):
        html = HTML.replace("espace de jeux pour enfants", "pas de jeux pour enfants")
        self.assertIsNone(build_draft(CITY, VENUE, ZIP, URL, html, OSM, ADMIN, DAY))

    def test_live_path_uses_same_pages_gate_and_fresh_append(self):
        class Registry:
            def read_text(self, **kwargs):
                return "{}"
        with patch("ptitesondes_place_preflight.private_json", return_value={}), \
             patch("ptitesondes_place_preflight.evaluate", return_value=(EMPTY, [])), \
             patch("ptitesondes_place_preflight.pinned_get", return_value='{"version":1,"updated_at":"2026-11-26","places":[]}'), \
             patch("ptitesondes_open_world_permanent_place_publisher_preview.read_private", return_value=state()), \
             patch("ptitesondes_open_world_permanent_place_publisher_preview.review_drafts",
                   return_value=([fresh()], {"rechecked":1,"complete_draft_records":1,"counts":{}})):
            result, outcomes = live_review("test", EMPTY, DAY, Registry())
        self.assertEqual(result["places"], [fresh()])
        self.assertEqual(outcomes[-1]["counts"]["open_world_added"], 1)


if __name__ == "__main__":
    unittest.main()
