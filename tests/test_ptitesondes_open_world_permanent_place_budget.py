"""Bounded live research must not pretend unprocessed leads were examined."""
from datetime import date
import unittest
from ptitesondes_open_world_permanent_place_research import (
    research, cycle, MAX_BATCH, public_diagnostic_lines,
)
from test_ptitesondes_open_world_permanent_place_research import row, report

DAY = date(2026, 11, 26)


class PlaceResearchBudgetTests(unittest.TestCase):
    def test_live_batch_can_examine_36_distinct_places(self):
        candidates = report(*(row("Lieu " + str(i)) for i in range(40)))
        seen = []
        def empty(city, venue):
            seen.append(venue)
            return {"elements": []}
        state, summary = cycle(candidates, None, DAY, limit=MAX_BATCH,
                               time_budget=600, clock=lambda: 0,
                               stop_on_outage=True, osm_fetch=empty)
        self.assertEqual(MAX_BATCH, 36)
        self.assertEqual(summary["examined"], 36)
        self.assertEqual(summary["unattempted"], 4)
        self.assertEqual(len(set(seen)), 36)
        self.assertEqual(summary["stop_reason"], "batch_complete")
        self.assertFalse(summary["publication_ready"])
        state, summary = cycle(candidates, state, DAY, limit=4, osm_fetch=empty)
        self.assertEqual(len(set(seen)), 40)
        self.assertEqual(summary["unattempted"], 0)

    def test_elapsed_budget_keeps_untouched_candidates_unattempted(self):
        candidates = report(*(row("Lieu " + str(i)) for i in range(10)))
        ticks = iter([0, 0, 8, 11])
        _, cursor, summary = research(candidates, None, DAY, limit=10,
            time_budget=10, clock=lambda: next(ticks),
            osm_fetch=lambda *_: {"elements": []})
        self.assertEqual(summary["examined"], 2)
        self.assertEqual(summary["unattempted"], 8)
        self.assertEqual(summary["stop_reason"], "time_budget")
        self.assertEqual(len(cursor["attempts"]), 2)

    def test_outage_stops_after_three_attempts_and_resumes_fairly(self):
        candidates = report(*(row("Lieu " + str(i)) for i in range(10)))
        seen = []
        def outage(city, venue):
            seen.append(venue)
            raise OSError("unavailable")
        _, cursor, summary = research(candidates, None, DAY, limit=10,
            stop_on_outage=True, osm_fetch=outage)
        self.assertEqual(summary["examined"], 3)
        self.assertEqual(summary["stop_reason"], "provider_outage")
        self.assertEqual(summary["unattempted"], 7)
        _, _, summary = research(candidates, cursor, DAY, limit=10,
            stop_on_outage=True, osm_fetch=outage)
        self.assertEqual(len(set(seen)), 6)
        self.assertEqual(summary["unattempted"], 4)

    def test_public_diagnostics_distinguish_outage_from_no_match(self):
        summary = {
            "stop_reason": "provider_outage",
            "counts": {"research_source_unavailable": 3,
                       "map_identity_missing_or_ambiguous": 2,
                       "independent_evidence_found": 1},
            "osm_transport": {"named.fossgis.http_429": 1,
                              "named.private_coffee.timeout": 2,
                              "named.fossgis.cooldown": 2},
        }
        self.assertEqual(public_diagnostic_lines(summary), [
            "stop_reason: provider_outage",
            "counts.map_identity_missing_or_ambiguous: 2",
            "counts.independent_evidence_found: 1",
            "counts.research_source_unavailable: 3",
            "osm_transport.named.fossgis.cooldown: 2",
            "osm_transport.named.fossgis.http_429: 1",
            "osm_transport.named.private_coffee.timeout: 2",
        ])

    def test_public_diagnostics_never_forward_unknown_text_or_keys(self):
        summary = {
            "stop_reason": "private venue / https://secret.example",
            "counts": {"private venue": 3, "research_source_unavailable": True,
                       "independent_evidence_found": "private venue"},
            "osm_transport": {"named.fossgis.private_url": 2,
                              "named.private_coffee.timeout": -1,
                              "named.fossgis.success": 10001},
        }
        self.assertEqual(public_diagnostic_lines(summary), [])

    def test_invalid_time_budget_rejected(self):
        for bad in (0, 601, True, "10"):
            with self.assertRaises(ValueError):
                research(report(row()), None, DAY, time_budget=bad)


if __name__ == "__main__":
    unittest.main()
