"""Offline safety and proof-contract tests for the public browser probe."""
import json
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_official_browser_probe import (
    compare_proof, request_allowed, trusted_parent, probe_sources,
    bounded_rendered_html, BrowserEvidenceError, MAX_DOM_BYTES,
    MAX_COMPACTION_INPUT_BYTES,
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

    def test_http_failure_does_not_skip_browser(self):
        def failed(*args, **kwargs):
            raise OSError("HTTP 403")
        result = probe_sources(PARENT, 2027, date(2026, 11, 19),
                               raw_fetch=failed, browser_fetch=lambda url: VISIBLE)
        self.assertEqual(result["verdict"], "RENDERED_DOM_CANDIDATE_ONLY")
        self.assertFalse(result["raw_available"])
        self.assertTrue(result["browser_available"])
        self.assertFalse(result["publication_authorized"])

    def test_browser_failure_preserves_raw_diagnostic(self):
        def failed(*args, **kwargs):
            raise OSError("browser unavailable")
        result = probe_sources(PARENT, 2027, date(2026, 11, 19),
                               raw_fetch=lambda *a, **k: VISIBLE, browser_fetch=failed)
        self.assertEqual(result["verdict"], "RAW_CANDIDATE_BROWSER_UNAVAILABLE")
        self.assertTrue(result["raw_candidate"])
        self.assertFalse(result["browser_available"])
        self.assertFalse(result["safe_to_publish"])

    def test_both_fail_closed(self):
        def failed(*args, **kwargs):
            raise OSError("unavailable")
        result = probe_sources(PARENT, 2027, date(2026, 11, 19),
                               raw_fetch=failed, browser_fetch=failed)
        self.assertEqual(result["verdict"], "BROWSER_OR_HTTP_UNAVAILABLE")
        self.assertFalse(result["rendered_candidate"])
        self.assertFalse(result["publication_authorized"])

    def test_jsonld_alone_cannot_be_mistaken_for_visible_rendered_dates(self):
        structured_only = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"MusicEvent",'
            '"name":"Festival 666 2027","startDate":"2027-08-13",'
            '"endDate":"2027-08-15"}</script>'
        )
        result = compare_proof(PARENT, 2027, date(2026, 11, 19),
                               SCRIPT_ONLY, structured_only)
        self.assertEqual(result["verdict"], "NO_BROWSER_VISIBLE_PROOF")
        self.assertFalse(result["rendered_candidate"])

    def test_wrong_edition_or_missing_visible_date_not_a_proof(self):
        today = date(2026, 11, 19)
        wrong = VISIBLE.replace("2027", "2028")
        self.assertFalse(compare_proof(
            PARENT, 2027, today, SCRIPT_ONLY, wrong)["rendered_candidate"])
        self.assertFalse(compare_proof(
            PARENT, 2027, today, SCRIPT_ONLY, "<h1>Festival 666 2027</h1>"
        )["rendered_candidate"])


    def test_small_dom_stays_byte_for_byte_identical(self):
        html = VISIBLE + "<script>var a = 1;</script>"
        self.assertEqual(bounded_rendered_html(html), html)

    def test_oversized_executable_payload_preserves_all_evidence(self):
        prefix = ('<html><head><style>.old{display:none}</style>'
                  '<script type="application/ld+json">'
                  '{"@type":"MusicEvent","name":"Festival 666 2027"}'
                  '</script><script type="application/json">{"edition":2027}</script>'
                  '<script type="module" data-marker="keep">')
        suffix = ('</script></head><body><main><h1>Festival 666</h1>'
                  '<h2>13 - 14 - 15 | AOUT | 2027</h2>'
                  '<p class="old" hidden>13 AOUT 2028</p>'
                  '<div aria-hidden="true"><a href="/old">Old band</a></div>'
                  '<p style="display:none">999 euros</p>'
                  '<a href="/lineup">Programmation</a>'
                  '<img src="/poster.png" alt="Affiche 2027">'
                  '</main></body></html>')
        html = prefix + ("//é\n" * 400_000) + suffix
        reduced = bounded_rendered_html(html)
        self.assertEqual(reduced, prefix + " " + suffix)
        # Compaction must preserve the independent validator's verdict,
        # not force a positive result for an ambiguous synthetic fixture.
        baseline = prefix + " " + suffix
        self.assertEqual(compare_proof(PARENT, 2027, date(2026, 11, 19),
                                       SCRIPT_ONLY, reduced),
                         compare_proof(PARENT, 2027, date(2026, 11, 19),
                                       SCRIPT_ONLY, baseline))
        # Also exercise a known positive fixture independently.
        positive = bounded_rendered_html(
            VISIBLE + "<script>" + "x" * MAX_DOM_BYTES + "</script>")
        self.assertEqual(compare_proof(PARENT, 2027, date(2026, 11, 19),
                                       SCRIPT_ONLY, positive)["verdict"],
                         "RENDERED_DOM_CANDIDATE_ONLY")

    def test_raw_text_cannot_be_reinterpreted_as_script_markup(self):
        raw = '<xmp><script>' + 'x' * 2000 + '</script></xmp>'
        html = '<script>' + 'x' * MAX_DOM_BYTES + '</script>' + raw + VISIBLE
        self.assertEqual(bounded_rendered_html(html),
                         '<script> </script>' + raw + VISIBLE)

    def test_structured_data_and_visible_overflow_fail_closed(self):
        for html in (
                '<script type="application/ld+json">' + 'x' * MAX_DOM_BYTES + '</script>',
                '<script type="application/json">' + 'x' * MAX_DOM_BYTES + '</script>',
                '<script language="unknown">' + 'x' * MAX_DOM_BYTES + '</script>',
                '<main>' + 'é' * MAX_DOM_BYTES + '</main>',
                '<script>' + 'x' * MAX_COMPACTION_INPUT_BYTES + '</script>',
                ''):
            with self.subTest(size=len(html)):
                with self.assertRaises(BrowserEvidenceError) as caught:
                    bounded_rendered_html(html)
                expected = ("invalid_bounded_dom" if not html else
                            "dom_input_over_limit" if len(html.encode("utf-8")) > MAX_COMPACTION_INPUT_BYTES
                            else "dom_compaction_insufficient")
                self.assertEqual(caught.exception.reason, expected)


if __name__ == "__main__":
    unittest.main()
