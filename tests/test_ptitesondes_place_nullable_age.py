"""Unknown age range must never turn into an invented 0–18 recommendation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_places import validate, assert_append_only


def catalogue():
    return json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))


class UnknownPlaceAgeTests(unittest.TestCase):
    def test_explicit_pair_of_unknown_ages_is_compatible_with_v1(self):
        old = catalogue()
        self.assertEqual(validate(old), len(old["places"]))
        document = deepcopy(old)
        document["places"][0]["age_min"] = None
        document["places"][0]["age_max"] = None
        self.assertEqual(validate(document), len(old["places"]))
        self.assertEqual(document["version"], 1)

    def test_partial_null_or_invalid_ages_are_not_accepted(self):
        for low, high in ((None, 18), (0, None), (False, 10),
                          (0, True), ("0", "18"), (4, 19), (-1, 6), (8, 4)):
            case = catalogue()
            case["places"][0]["age_min"] = low
            case["places"][0]["age_max"] = high
            with self.subTest(age_min=low, age_max=high), self.assertRaises(ValueError):
                validate(case)

    def test_unknown_age_does_not_grant_automatic_historical_edits(self):
        original = catalogue()
        altered = deepcopy(original)
        altered["places"][0]["age_min"] = None
        altered["places"][0]["age_max"] = None
        with self.assertRaisesRegex(ValueError, "modifié"):
            assert_append_only(original, altered)

    def test_no_fictitious_session_when_ages_are_unknown(self):
        altered = catalogue()
        altered["places"][0]["age_min"] = None
        altered["places"][0]["age_max"] = None
        altered["places"][0]["sessions"] = ["2026-11-05"]
        with self.assertRaises(ValueError):
            validate(altered)

    def test_demo_popup_explains_unknown_age_without_defaulting_to_0_18(self):
        html = (ROOT / "docs/ptitesondes/carte-lieux.html").read_text(encoding="utf-8")
        self.assertIn("Âges non précisés", html)
        self.assertIn("p.age_min == null || p.age_max == null", html)


if __name__ == "__main__":
    unittest.main()
