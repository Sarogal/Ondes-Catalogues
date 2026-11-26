from copy import deepcopy
from datetime import date
from unittest.mock import patch
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import CITY, VENUE, HTML, OSM, URL
from ptitesondes_open_world_permanent_place_research import STATE_SCHEMA
from ptitesondes_open_world_permanent_place_publisher_preview import review

DAY = date(2026, 11, 26)


def state():
    return {"schema": STATE_SCHEMA, "records": [{
        "city": CITY, "venue": VENUE, "public_eligible": False,
        "status": "independent_evidence_found",
        "evidence": {"public_eligible": False, "lat": 0, "lng": 0,
                     "official_url": "https://untrusted.example/forged",
                     "osm_object": "node/999999"},
    }]}


class OpenWorldPlacePublisherPreviewTests(unittest.TestCase):
    def test_fresh_sources_not_private_claims(self):
        visited = []
        s = state()
        with patch("ptitesondes_open_world_permanent_place_publisher_preview.approved_municipal_page_host",
                   return_value="venue.example"):
            result = review(s, DAY, osm_fetch=lambda *_: OSM,
                            directory_fetch=lambda _: {},
                            page_read=lambda url: visited.append(url) or HTML)
        self.assertEqual(visited, [URL])
        self.assertEqual(result["independently_corroborated"], 1)
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn(VENUE, str(result))
        self.assertEqual(s, state())

    def test_unknown_host_is_not_read_by_publisher(self):
        with patch("ptitesondes_open_world_permanent_place_publisher_preview.approved_municipal_page_host",
                   return_value=None):
            result = review(state(), DAY, osm_fetch=lambda *_: OSM,
                            directory_fetch=lambda _: {},
                            page_read=lambda _: self.fail("unauthenticated read"))
        self.assertEqual(result["independently_corroborated"], 0)

    def test_no_reliance_on_cached_private_proof(self):
        with patch("ptitesondes_open_world_permanent_place_publisher_preview.approved_municipal_page_host",
                   return_value="venue.example"):
            result = review(state(), DAY, osm_fetch=lambda *_: OSM,
                            directory_fetch=lambda _: {},
                            page_read=lambda _: HTML.replace("Ouverte à tous", "Sur invitation"))
        self.assertEqual(result["independently_corroborated"], 0)

    def test_forged_permission_and_duplicate_rejected(self):
        s = state()
        s["records"][0]["public_eligible"] = True
        with self.assertRaises(ValueError):
            review(s, DAY)
        s = state()
        s["records"].append(deepcopy(s["records"][0]))
        with self.assertRaises(ValueError):
            review(s, DAY)

    def test_missing_initial_state_is_nonblocking(self):
        result = review(None, DAY)
        self.assertEqual(result["counts"], {"private_research_not_yet_available": 1})
        self.assertEqual(result["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
