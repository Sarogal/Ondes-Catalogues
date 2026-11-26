from datetime import date
from copy import deepcopy
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import (
    CITY, VENUE, URL, HTML, OSM,
)
from ptitesondes_open_world_permanent_place_research import named_query, research

DAY = date(2026, 11, 26)


def row(venue=VENUE, city=CITY, status="historical_directory_needs_current_proof"):
    return {"city": city, "venue": venue, "status": status,
            "public_eligible": False, "gps_verified": False,
            "official_site_verified": False}


def report(*rows):
    return {"schema": "ptitesondes.place_review.v1", "records": list(rows)}


class OpenWorldPermanentPlaceResearchTests(unittest.TestCase):
    def test_unknown_historical_place_needs_no_uid_or_registry(self):
        results, state, summary = research(report(row()), None, DAY,
            osm_fetch=lambda *_: OSM, page_read=lambda _: HTML)
        self.assertEqual(summary["counts"], {"independent_evidence_found": 1})
        self.assertFalse(results[0]["public_eligible"])
        self.assertFalse(results[0]["evidence"]["public_eligible"])
        self.assertEqual(summary["public_writes"], 0)
        self.assertEqual(len(state["attempts"]), 1)
        self.assertNotIn(VENUE, str(summary))

    def test_every_candidate_rotates_even_after_network_failure(self):
        rows = [row("Lieu " + str(i)) for i in range(9)]
        rows.append(row("Published", status="already_public"))
        seen = []
        state = None
        def fail(city, venue):
            seen.append(venue)
            raise OSError("private diagnostic")
        for _ in range(3):
            result, state, summary = research(report(*rows), state, DAY,
                limit=3, osm_fetch=fail, page_read=lambda _: HTML)
            self.assertEqual(summary["counts"], {"research_source_unavailable": 3})
        self.assertEqual(len(set(seen)), 9)
        self.assertEqual(summary["unattempted"], 0)
        research(report(*rows), state, DAY, limit=1, osm_fetch=fail)
        self.assertEqual(seen[0], seen[-1])

    def test_conflicting_website_never_read(self):
        osm = deepcopy(OSM)
        osm["elements"][0]["tags"]["contact:website"] = "https://other.example/a"
        def forbidden(_):
            self.fail("must not visit conflicting website")
        _, _, summary = research(report(row()), None, DAY,
                                  osm_fetch=lambda *_: osm, page_read=forbidden)
        self.assertEqual(summary["counts"], {"map_website_missing_or_conflicting": 1})

    def test_mismatching_postcode_stays_private(self):
        r = dict(row(), historical_address_unverified={"postal_code": "54321"})
        _, _, summary = research(report(r), None, DAY, osm_fetch=lambda *_: OSM,
                                  page_read=lambda _: self.fail("unexpected read"))
        self.assertEqual(summary["counts"], {"postal_evidence_conflict": 1})

    def test_input_injection_and_permission_flags(self):
        query = named_query('Ville";out;', 'Lieu "test"')
        self.assertIn(r'Ville\";out;', query)
        with self.assertRaises(ValueError):
            named_query("Ville\n", VENUE)
        with self.assertRaises(ValueError):
            research(report(dict(row(), public_eligible=True)), None, DAY)
        with self.assertRaises(ValueError):
            research(report(row(), row()), None, DAY)


if __name__ == "__main__":
    unittest.main()
