import unittest
from go_radio_v8_metadata_second_pass import format_kind


class FormatEvidenceTests(unittest.TestCase):
    def test_current_separators(self):
        for sep in (" - ", " – ", " — "):
            self.assertEqual(format_kind("Metallica" + sep + "One", "Radio"),
                             "current_parser_pair")

    def test_candidates_are_not_asserted_artist_pairs(self):
        for sep in (" | ", " : ", " / ", " ~ "):
            self.assertEqual(format_kind("Artist" + sep + "Title", "Radio"),
                             "alternative_separator_candidate")

    def test_station_label_precedes_separator(self):
        self.assertEqual(format_kind(" Radio - Metal ", "radio - metal"),
                         "station_name_only")

    def test_single_and_empty(self):
        self.assertEqual(format_kind("Song", "Radio"), "unsplit")
        self.assertEqual(format_kind("   ", "Radio"), "empty")


if __name__ == "__main__":
    unittest.main()
