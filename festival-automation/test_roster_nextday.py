"""Regression tests for independent, next-day artist-evidence rechecks."""
import copy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from official_watch import (
    choose_pending_rechecks, choose_sources, fingerprint,
    stable_roster_observation,
)
from roster_candidates import roster_proposal


ROW = {
    "slug": "metal-fest-2027",
    "name": "Metal Fest 2027",
    "startDate": "2027-08-19",
    "endDate": "2027-08-22",
    "officialSite": "https://metal-fest.example.org/",
    "lineup": ["First Band"],
    "bands": 1,
    "lastVerified": "2026-10-01",
}
URL = ROW["officialSite"]


def clue(artists=None, **extra):
    hints = {"new_performers": list(artists or ["Second Band"])}
    hints.update(extra)
    return [{
        "slug": ROW["slug"],
        "source_url": URL,
        "name_on_source": ROW["name"],
        "startDate_source": ROW["startDate"],
        "endDate_source": ROW["endDate"],
        "publication_authorized": False,
        "hints": hints,
    }]


class NextDayRosterProofTests(unittest.TestCase):
    def test_two_distinct_days_and_exact_same_artist_evidence(self):
        state = {}
        first = clue()
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, first, "2026-11-04"))
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, first, "2026-11-04"))
        self.assertTrue(stable_roster_observation(
            state, ROW["slug"], URL, first, "2026-11-05"))
        self.assertEqual(state["roster_candidate_observations"][ROW["slug"]]["firstSeen"], "2026-11-04")
        self.assertEqual(
            roster_proposal(ROW, ROW, first,
                            {"sha256": "same", "lastChanged": "2026-11-04"},
                            "same", "2026-11-05")["changes"][0]["after"],
            ["First Band", "Second Band"])

    def test_changed_jsonld_while_visible_html_unchanged_restarts_clock(self):
        a = "<main>" + "Festival officiel. " * 20 + "</main>"
        self.assertEqual(fingerprint(a + "<script>first version</script>"),
                         fingerprint(a + "<script>second version</script>"))
        state = {}
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, clue(["Second Band"]), "2026-11-04"))
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, clue(["Third Band"]), "2026-11-05"))
        self.assertTrue(stable_roster_observation(
            state, ROW["slug"], URL, clue(["Third Band"]), "2026-11-06"))

    def test_gap_resets_two_day_certificate(self):
        state = {}
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, clue(), "2026-11-04"))
        self.assertFalse(stable_roster_observation(
            state, ROW["slug"], URL, clue(), "2026-11-06"))

    def test_ambiguous_or_sensitive_clues_are_never_certified(self):
        for clues in (
            clue() + clue(["Other"]),
            clue(status="EventCancelled"),
            clue(new_performers=[]),
            [dict(clue()[0], source_url="https://unauthorized.example.org/")],
            [dict(clue()[0], publication_authorized=True)],
        ):
            state = {}
            self.assertFalse(stable_roster_observation(
                state, ROW["slug"], URL, clues, "2026-11-04"))
            self.assertFalse(stable_roster_observation(
                state, ROW["slug"], URL, clues, "2026-11-05"))
            self.assertNotIn(ROW["slug"], state["roster_candidate_observations"])

    def test_programming_priority_keeps_other_sources_in_rotation(self):
        doc = {"schema": 1, "festivals": [
            {"slug": "festival-" + str(i),
             "officialSite": "https://festival" + str(i) + ".example.org/",
             "startDate": "2027-08-19"} for i in range(100)]}
        today = date(2026, 11, 5)
        yesterday = date(2026, 11, 4)
        ordinary = choose_sources(doc, today, "primary", 12)
        prior = choose_sources(doc, yesterday, "primary", 12)
        target = next(url for _, url in prior if url not in {u for _, u in ordinary})
        state = {"roster_candidate_observations": {
            "festival-99": {"source": target, "lastSeen": "2026-11-04",
                            "digest": "verified-candidate"}}}
        selected = choose_pending_rechecks(doc, today, "primary", 12, state)
        self.assertEqual(len(selected), 12)
        self.assertIn(target, [url for _, url in selected])
        self.assertGreaterEqual(
            len({u for _, u in selected} & {u for _, u in ordinary}), 11)
        self.assertEqual(choose_pending_rechecks(
            doc, date(2026, 11, 7), "primary", 12, state),
            choose_sources(doc, date(2026, 11, 7), "primary", 12))
        state["roster_candidate_observations"]["festival-99"]["source"] = "https://outside.example.org/"
        self.assertEqual(choose_pending_rechecks(
            doc, today, "primary", 12, state), ordinary)

    def test_corrupt_roster_state_fails_closed(self):
        doc = {"schema": 1, "festivals": [
            {"slug": "festival-" + str(i),
             "officialSite": "https://festival" + str(i) + ".example.org/"}
            for i in range(100)]}
        with self.assertRaisesRegex(ValueError, "invalide"):
            choose_pending_rechecks(
                doc, date(2026, 11, 5), "primary", 12,
                {"roster_candidate_observations": []})


if __name__ == "__main__":
    unittest.main()
