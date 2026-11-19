"""Offline safety and proof-contract tests for the public browser probe."""
import json
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_official_browser_probe import (
    compare_proof, request_allowed, trusted_parent,
)

PARENT = {
    "slug": "festival-666", "name": "Festival 666",
    "officialSite": "https://www.festival666.com/",
    "startDate": "2026-08-07", "endDate": "2026-08-09",
    "lastKnownYear": 2026,
}
VISIBLE = (
    "<html><body><main><h2>13 - 14 - 15 | AOUT | 2027</h2>"
    "<h1>Festival 666</h1></main></body></html>"
)
SCRIPT_ONLY = (
    "<html><head><script>const year = '2027';</script></head>"
    "<body><h1>Festival 666</h1><p>Dates à venir</p></body></html>"
)


class BrowserPreflightTests(unittest.TestCase):
    def test_archive_only_and_source_identity_are_required(self):
        parent, year = trusted_parent({"schema": 2, "knownFestivals": [PARENT]},
                                      "festival-666")
        self.assertEqual(parent, PARENT)
        self.assertEqual(year, 2027)
        for entries in ([], [PARENT, PARENT],
                        [dict(PARENT, officialSite="http://www.festival666.com/")],
                        [dict(PARENT, officialSite="https://localhost/")],
                        [dict(PARENT, lastKnownYear=2025)]):
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    trusted_parent({"schema": 2, "knownFestivals": entries},
                                   "festival-666")

    def test_browser_request_guard_blocks_cross_origin_and_unsafe_scheme(self):
        source = PARENT["officialSite"]
        self.assertTrue(request_allowed(source, source))
        self.assertTrue(request_allowed(
            "https://www.festival666.com/assets/app.js", source))
        for url in ("http://www.festival666.com/", "https://evil.example/",
                    "https://festival666.com/", "https://www.festival666.com:444/",
                    "https://user:pass@www.festival666.com/",
                    "file:///etc/passwd", "https://localhost/"):
            with self.subTest(url=url):
                self.assertFalse(request_allowed(url, source))

    def test_only_rendered_dom_can_upgrade_the_diagnostic(self):
        today = date(2026, 11, 19)
        only_render = compare_proof(PARENT, 2027, today, SCRIPT_ONLY, VISIBLE)
        self.assertEqual(only_render["verdict"], "RENDERED_DOM_CANDIDATE_ONLY")
        self.assertFalse(only_render["raw_candidate"])
        self.assertTrue(only_render["rendered_candidate"])
        for flag in ("safe_to_publish", "publication_authorized",
                     "publisher_independent_recheck"):
            self.assertFalse(only_render[flag])
        self.assertEqual(
            compare_proof(PARENT, 2027, today, VISIBLE, VISIBLE)["verdict"],
            "RAW_AND_RENDERED_CANDIDATE_ONLY")
        self.assertEqual(
            compare_proof(PARENT, 2027, today, SCRIPT_ONLY, SCRIPT_ONLY)["verdict"],
            "NO_BROWSER_VISIBLE_PROOF")
        self.assertNotIn("festival666.com", json.dumps(only_render))
        self.assertNotIn("2027-08-13", json.dumps(only_render))

    def test_wrong_edition_or_missing_visible_date_not_a_proof(self):
        today = date(2026, 11, 19)
        wrong = VISIBLE.replace("2027", "2028")
        self.assertFalse(compare_proof(
            PARENT, 2027, today, SCRIPT_ONLY, wrong)["rendered_candidate"])
        self.assertFalse(compare_proof(
            PARENT, 2027, today, SCRIPT_ONLY, "<h1>Festival 666 2027</h1>"
        )["rendered_candidate"])


if __name__ == "__main__":
    unittest.main()
