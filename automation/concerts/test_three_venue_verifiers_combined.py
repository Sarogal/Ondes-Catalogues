"""Combined isolated regression for BBC, Cave aux Poètes and Bonjour Minuit.

Each unrelated source must reach the same independent publisher without
introducing a venue-specific bypass or an artificial artist-count ceiling.
These are synthetic events and never modify private or public catalogues.
"""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import official_recheck
import test_bbc_official_recheck as bbc
import test_cave_poetes_official_recheck as cave
import test_bonjour_minuit_official_recheck as bonjour
from concerts_cloud_sync import validate_approval


class ThreeVenueVerifierIntegrationTests(unittest.TestCase):
    def test_all_three_synthetic_first_party_bills_pass_same_gate(self):
        today = dt.date(2026, 11, 18)
        catalogue = {
            "schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [
                copy.deepcopy(bbc.VENUE),
                copy.deepcopy(cave.VENUE),
                copy.deepcopy(bonjour.VENUE),
            ],
            "artists": [], "events": [],
        }
        bbc_html = bbc.html_bill(["ACT 01", "ACT 02"])
        cave_names = ("CAVE BAND 01", "CAVE BAND 02")
        cave_html = cave.html(cave_names)
        bonjour_html = bonjour.show(("MINUIT BAND 01", "MINUIT BAND 02"))
        cases = [
            (bbc.discovery(bbc_html), bbc_html,
             "big-band-cafe-herouville", None, 2),
            (cave.candidate(cave_html, cave_names), cave_html,
             "la-cave-aux-poetes-roubaix", "20:00", 2),
            (bonjour.discovery(bonjour_html), bonjour_html,
             "bonjour-minuit-saint-brieuc", None, 2),
        ]
        approvals = []
        for candidate, html, expected_venue, expected_time, artist_count in cases:
            with self.subTest(source=candidate["source"]):
                approval = official_recheck.verify(
                    candidate, html, catalogue, today)
                published, created = validate_approval(
                    approval,
                    {v["id"]: v for v in catalogue["venues"]},
                    {a["id"]: a for a in catalogue["artists"]},
                    today,
                )
                self.assertEqual(published["venueId"], expected_venue)
                self.assertEqual(published["time"], expected_time)
                self.assertEqual(len(published["artistIds"]), artist_count)
                self.assertEqual(len(created), artist_count)
                self.assertEqual(published["artistIds"],
                                 approval["event"]["artistIds"])
                approvals.append(approval)
        self.assertEqual(len({a["event"]["id"] for a in approvals}), 3)
        self.assertEqual(
            len({a["event"]["officialUrl"] for a in approvals}), 3)
        self.assertEqual(
            len({artist["id"] for approval in approvals
                 for artist in approval["newArtists"]}), 6)
        self.assertEqual(catalogue["events"], [])
        self.assertEqual(catalogue["artists"], [])


if __name__ == "__main__":
    unittest.main()
