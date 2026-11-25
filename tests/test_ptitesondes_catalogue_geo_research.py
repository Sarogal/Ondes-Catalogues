from copy import deepcopy
from datetime import date
import unittest
from ptitesondes_catalogue_geo_research import research_queue

TODAY = date(2026, 11, 25)


def e(id, venue="Salle A", **kw):
    return dict(id=id, city="Villeurbanne", venue=venue, date_start="2026-12-01", **kw)


class GeoResearchTests(unittest.TestCase):
    def test_hints_and_no_mutation(self):
        doc = dict(events=[e("a"), e("old", lat=45.7, lng=4.8, date_end="2026-11-01")])
        snapshot = deepcopy(doc)
        r = research_queue(doc, TODAY)
        self.assertEqual(r["active_without_valid_point"], 1)
        g = r["research_groups"][0]
        self.assertEqual(g["missing_ids"], ["a"])
        self.assertEqual(g["point_hints"][0]["event_ids"], ["old"])
        self.assertTrue(g["independent_proof_required"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(doc, snapshot)

    def test_conflicting_points_are_only_research(self):
        r = research_queue(dict(events=[e("a", lat=45.7, lng=4.8),
            e("b", "Salle B", lat=45.7, lng=4.8), e("c", lat=46, lng=4.8)]), TODAY)
        self.assertEqual(r["shared_exact_points"], 1)
        self.assertEqual(len(r["research_groups"]), 2)
        self.assertIn("inconsistent_same_venue_points", r["research_groups"][0]["reasons"])
        self.assertEqual(r["public_writes"], 0)

    def test_no_homonym_match_and_bad_points(self):
        r = research_queue(dict(events=[e("a", department="01"),
            e("b", department="02", lat=45.7, lng=4.8),
            e("c", "", lat=True, lng=4.8), e("d", "Other", lat=91, lng=0)]), TODAY)
        self.assertEqual(r["active_without_valid_point"], 3)
        self.assertEqual(r["incomplete_identity_ids"], ["c"])
        self.assertEqual(next(g for g in r["research_groups"] if g["missing_ids"] == ["a"])["point_hints"], [])

    def test_duplicate_ids(self):
        with self.assertRaises(ValueError):
            research_queue(dict(events=[e("a"), e("a")]), TODAY)
