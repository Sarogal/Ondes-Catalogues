"""Tests du simulateur de migration des favoris V64 -> GO."""
import copy
import unittest

from radio_catalog_favorites_preview import build_lookup, preview_favorites


class FavoritePreviewTest(unittest.TestCase):
    def setUp(self):
        self.index = [
            {"legacy_id": "old-primary", "go_station_id": "go-station-000001"},
            {"legacy_id": "old-variant", "go_station_id": "go-station-000001"},
            {"legacy_id": "old-two", "go_station_id": "go-station-000002"},
            {"legacy_id": "old-three", "go_station_id": "go-station-000003"},
        ]
        self.lookup = build_lookup({"aliases": self.index})

    def test_two_old_uuids_map_to_one_go_favorite(self):
        original = ["old-primary", "old-variant", "old-two"]
        before = copy.deepcopy(original)
        result = preview_favorites(original, self.lookup)
        self.assertEqual(original, before)
        self.assertEqual(result["legacy_favorites_unchanged"], before)
        self.assertEqual(result["go_station_ids_preview"],
                         ["go-station-000001", "go-station-000002"])
        self.assertFalse(result["safe_to_delete_old_favorites"])

    def test_unknown_favorite_survives_and_is_not_discarded(self):
        result = preview_favorites(["missing-old-uuid", "old-two"], self.lookup)
        self.assertEqual(result["unresolved_legacy_ids_kept"], ["missing-old-uuid"])
        self.assertEqual(len(result["legacy_favorites_unchanged"]), 2)
        self.assertEqual(result["go_station_ids_preview"], ["go-station-000002"])

    def test_quarantined_and_retired_remain_favorites(self):
        states = {"go-station-000001": "quarantined",
                  "go-station-000003": "retired"}
        result = preview_favorites(["old-primary", "old-three"], self.lookup, states)
        self.assertEqual(result["quarantined_still_favorited"], ["go-station-000001"])
        self.assertEqual(result["retired_still_favorited"], ["go-station-000003"])

    def test_already_migrated_goid_is_recognized(self):
        result = preview_favorites(["go-station-000001", "old-variant"], self.lookup)
        self.assertEqual(result["go_station_ids_preview"], ["go-station-000001"])

    def test_collision_refused(self):
        index = [*self.index, {"legacy_id": "old-variant", "go_station_id": "go-station-099999"}]
        with self.assertRaisesRegex(ValueError, "alias collision"):
            build_lookup(index)


if __name__ == "__main__":
    unittest.main()
