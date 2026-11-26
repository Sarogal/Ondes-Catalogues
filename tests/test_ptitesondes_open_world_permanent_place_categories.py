"""Dedicated permanent cultural places; incidental events are not enough."""
from copy import deepcopy
from datetime import date
import unittest
from test_ptitesondes_open_world_permanent_place_evidence import CITY, VENUE, ZIP, URL, HTML, OSM
from test_ptitesondes_open_world_permanent_place_draft import ADMIN
from ptitesondes_open_world_permanent_place_draft import build_draft
from ptitesondes_open_world_permanent_place_research import research
from test_ptitesondes_open_world_permanent_place_research import row, report

DAY = date(2026, 11, 26)


def fixture(name, tags, description):
    osm = deepcopy(OSM)
    node = osm["elements"][0]["tags"]
    del node["amenity"]
    node.update(tags, name=name)
    html = HTML.replace(VENUE, name).replace(
        "Ouverte à tous, espace de jeux pour enfants.",
        "Ouvert à tous. " + description)
    return osm, html


class PlaceCategoriesTests(unittest.TestCase):
    def test_dedicated_categories_publishable_drafts(self):
        for name, tags, text, expected in (
            ("Musée des enfants", {"tourism": "museum"},
             "Ce musée est un musée dédié aux enfants. Expositions interactives pour les enfants.",
             "musee-enfants"),
            ("Théâtre des petits", {"amenity": "theatre"},
             "Notre théâtre jeune public propose des spectacles pour les enfants.",
             "theatre-jeune-public"),
            ("Maison des arts", {"amenity": "arts_centre"},
             "Un centre d'éveil artistique. Éveil artistique et ateliers pour les enfants.",
             "centre-eveil-artistique"),
        ):
            with self.subTest(name=name):
                osm, html = fixture(name, tags, text)
                result = build_draft(CITY, name, ZIP, URL, html, osm, ADMIN, DAY)
                self.assertIsNotNone(result)
                self.assertEqual(result["category"], expected)
                _, _, summary = research(report(row(name)), None, DAY,
                    osm_fetch=lambda *_: osm, page_read=lambda _: html)
                self.assertEqual(summary["counts"], {"independent_evidence_found": 1})

    def test_incidental_youth_activities_do_not_change_generic_place_category(self):
        for tags in ({"tourism": "museum"}, {"amenity": "theatre"},
                     {"amenity": "arts_centre"}):
            osm, html = fixture("Lieu culturel", tags, "Ateliers pour les enfants en décembre.")
            self.assertIsNone(build_draft(CITY, "Lieu culturel", ZIP, URL,
                                          html, osm, ADMIN, DAY))

    def test_restricted_and_ambiguous_mapped_features_stay_private(self):
        for tags in ({"tourism": "museum", "amenity": "theatre"},
                     {"tourism": "museum", "access": "private"},
                     {"amenity": "school"}):
            osm, html = fixture("Musée des enfants", tags,
                "Musée dédié aux enfants. Ateliers pour les enfants.")
            self.assertIsNone(build_draft(CITY, "Musée des enfants", ZIP, URL,
                                          html, osm, ADMIN, DAY))


if __name__ == "__main__":
    unittest.main()
