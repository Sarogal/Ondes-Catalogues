from copy import deepcopy
from datetime import date
from unittest.mock import patch
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import CITY, VENUE, HTML, OSM, URL
from ptitesondes_open_world_permanent_place_research import STATE_SCHEMA
from test_ptitesondes_open_world_permanent_place_draft import ADMIN
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
                            page_read=lambda url: visited.append(url) or HTML,
                            admin_fetch=lambda *_: ADMIN)
        self.assertEqual(visited, [URL])
        self.assertEqual(result["independently_corroborated"], 1)
        self.assertEqual(result["complete_draft_records"], 1)
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn(VENUE, str(result))
        self.assertEqual(s, state())

    def test_numberless_osm_with_fresh_commune_authority(self):
        from test_ptitesondes_dila_municipal_domains import mairie, payload
        from ptitesondes_open_world_permanent_place_publisher_preview import review_drafts
        from ptitesondes_place_preflight import merge_open_world_drafts
        calls = []
        def directory(city, code):
            calls.append(code)
            return payload(mairie(city=CITY, site="https://venue.example/", insee=code))
        kwargs = dict(osm_fetch=lambda *_: OSM, directory_fetch=lambda _: payload(),
                      code_directory_fetch=directory,
                      commune_fetch=lambda _: [{"nom": CITY, "code": "12345"}],
                      page_read=lambda _: HTML, admin_fetch=lambda *_: ADMIN)
        drafts, result = review_drafts(state(), DAY, **kwargs)
        self.assertEqual(calls, ["12345"])
        self.assertEqual(result["counts"]["osm_directory_geo_found"], 1)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["address"], "Rue des Jeux, 12345 Ville")
        self.assertEqual((drafts[0]["lat"], drafts[0]["lng"]), (45.1, 3.1))
        out, counts = merge_open_world_drafts(
            {"version": 1, "updated_at": DAY.isoformat(), "places": []}, drafts, DAY)
        self.assertEqual(counts["open_world_added"], 1)
        self.assertEqual(len(out["places"]), 1)
        drafts, result = review_drafts(state(), DAY, **dict(kwargs,
            admin_fetch=lambda *_: [dict(ADMIN[0], code="99999")]))
        self.assertEqual(drafts, [])
        self.assertEqual(result["counts"]["osm_directory_geo_admin_conflict"], 1)
        calls.clear()
        drafts, result = review_drafts(state(), DAY, **dict(kwargs,
            commune_fetch=lambda _: [{"nom": CITY, "code": "12345"},
                                    {"nom": CITY, "code": "99999"}],
            osm_fetch=lambda *_: self.fail("ambiguous authority must not read OSM")))
        self.assertEqual(drafts, [])
        self.assertEqual(calls, [])
        self.assertEqual(result["counts"]["osm_directory_geo_unmatched"], 1)

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
