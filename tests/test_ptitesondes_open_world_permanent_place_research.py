from datetime import date
from copy import deepcopy
from unittest.mock import patch
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import (
    CITY, VENUE, URL, HTML, OSM,
)
from ptitesondes_open_world_permanent_place_research import named_query, research, cycle, typographic_query, fetch_named

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

    def test_private_cycle_retains_other_candidates_and_rejects_forged_approval(self):
        candidates = report(row(), row("Autre lieu"))
        state, first = cycle(candidates, None, DAY, limit=1,
                            osm_fetch=lambda *_: OSM, page_read=lambda _: HTML)
        state, second = cycle(candidates, state, DAY, limit=1,
                             osm_fetch=lambda *_: OSM, page_read=lambda _: HTML)
        self.assertEqual(first["stored_private_results"], 1)
        self.assertEqual(second["stored_private_results"], 2)
        self.assertEqual(second["unattempted"], 0)
        self.assertTrue(all(r["public_eligible"] is False for r in state["records"]))
        state["records"][0]["public_eligible"] = True
        with self.assertRaises(ValueError):
            cycle(candidates, state, DAY)

    def test_transport_outage_keeps_private_hint_without_refreshing_it(self):
        from datetime import timedelta
        candidates = report(row())
        state, _ = cycle(candidates, None, DAY,
                         osm_fetch=lambda *_: OSM, page_read=lambda _: HTML)
        original = deepcopy(state["records"][0])
        def unavailable(*_):
            raise OSError("private transport diagnostic")
        next_day = DAY + timedelta(days=1)
        for fetch in (unavailable, lambda *_: {"remark": "incomplete", "elements": []}):
            state, summary = cycle(candidates, state, next_day, osm_fetch=fetch)
            self.assertEqual(state["records"][0], original)
            self.assertEqual(summary["preserved_private_hints_on_outage"], 1)
            self.assertFalse(summary["publication_ready"])
            self.assertEqual(summary["public_writes"], 0)
        self.assertEqual(state["cursor"]["sequence"], 3)
        # A complete negative map response supersedes the old hint.
        state, summary = cycle(candidates, state, next_day,
                               osm_fetch=lambda *_: {"elements": []})
        self.assertEqual(summary["preserved_private_hints_on_outage"], 0)
        self.assertEqual(state["records"][0]["status"], "map_identity_missing_or_ambiguous")
        self.assertIsNone(state["records"][0]["evidence"])

    def test_no_longer_active_identity_drops_old_hint(self):
        state, _ = cycle(report(row()), None, DAY,
                         osm_fetch=lambda *_: OSM, page_read=lambda _: HTML)
        state, summary = cycle(report(row(status="already_public")), state, DAY)
        self.assertEqual(state["records"], [])
        self.assertEqual(summary["preserved_private_hints_on_outage"], 0)

    def test_typographic_query_expands_accents_case_and_punctuation(self):
        q = typographic_query("Saint-Étienne", "Médiathèque-Ludothèque")
        self.assertIn('[eéèêë]', q)
        self.assertIn('[[:space:][:punct:]’–—]+', q)
        self.assertIn('",i]', q)
        self.assertNotIn("Médiathèque-Ludothèque", q)
        with patch("ptitesondes_open_world_permanent_place_research.fetch_osm_query",
                   return_value=OSM) as provider:
            self.assertIs(fetch_named("Saint-Étienne", "Médiathèque-Ludothèque"), OSM)
        self.assertEqual(provider.call_args.args[0], q)

    def test_typographic_search_never_copies_regex_or_query_injection(self):
        q = typographic_query('Ville";out;', 'Lieu .* "test"')
        self.assertNotIn('";out;', q)
        self.assertNotIn('.*', q)
        with self.assertRaises(ValueError):
            typographic_query("Ville\n", VENUE)

    def test_normalized_homonyms_remain_ambiguous(self):
        osm = deepcopy(OSM)
        second = deepcopy(osm["elements"][0])
        second["id"] += 1
        second["tags"]["name"] = VENUE.upper()
        osm["elements"].append(second)
        _, _, summary = research(report(row()), None, DAY, osm_fetch=lambda *_: osm,
                                  page_read=lambda _: self.fail("ambiguous identity"))
        self.assertEqual(summary["counts"], {"map_identity_missing_or_ambiguous": 1})

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
