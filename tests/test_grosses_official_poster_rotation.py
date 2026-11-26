import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_official_poster_rotation import scan, contextual_poster_match

SITE = "https://festival-exemple.fr/"
ROW = {"slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
       "startDate": "2027-08-13", "endDate": "2027-08-15",
       "officialSite": SITE, "lineup": []}
CAT = {"schema": 1, "festivals": [ROW]}
HTML = '<main><img src="/exemple-2027.jpg"><img src="/poster-2027.jpg"><img src="/affiche-2027.jpg"></main>'


class RotationTests(unittest.TestCase):
    def test_only_discovered_same_host_and_bounded_no_publish(self):
        from copy import deepcopy
        original = deepcopy(CAT)
        reader = Mock(return_value={"status": "review_only", "review_only": True, "words": []})
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: HTML, reader=reader)
        self.assertEqual(report["images_read"], 2)
        self.assertTrue(all(call.args[0] == SITE and call.args[1].startswith(SITE)
                            for call in reader.call_args_list))
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(CAT, original)

    def test_rate_limit_stops_remaining_images_on_host(self):
        reader = Mock(return_value={"status": "rate_limited"})
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: HTML, reader=reader)
        self.assertEqual(report["images_read"], 1)
        reader.assert_called_once()

    def test_unknown_slug_or_external_img_never_read(self):
        reader = Mock()
        fetch = Mock(return_value='<main><img src="https://external.fr/poster-2027.jpg"></main>')
        scan(CAT, "2026-11-26", slug="unknown", fetch=fetch, reader=reader)
        fetch.assert_not_called()
        scan(CAT, "2026-11-26", slug=ROW["slug"], fetch=fetch, reader=reader)
        reader.assert_not_called()

    def test_rendered_fallback_uses_only_same_signed_origin(self):
        browser = Mock(return_value=HTML)
        reader = Mock(return_value={"status": "review_only", "review_only": True, "words": []})
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: "<main>Loading</main>",
                      reader=reader, browser_fetch=browser)
        browser.assert_called_once_with(SITE)
        self.assertEqual(report["browser_hosts"], 1)
        self.assertEqual(report["images_read"], 2)
        self.assertEqual(report["rows"][0]["raw_candidates"], 0)
        self.assertEqual(report["rows"][0]["rendered_candidates"], 3)

    def test_no_browser_after_http_failure_or_when_raw_has_candidates(self):
        from dns_pinned_https import OfficialHTTPStatusError
        browser = Mock()
        reader = Mock(return_value={"status": "rate_limited"})
        scan(CAT, "2026-11-26", tick=0, fetch=Mock(side_effect=OfficialHTTPStatusError(429)),
             reader=reader, browser_fetch=browser)
        browser.assert_not_called()
        reader.assert_not_called()
        scan(CAT, "2026-11-26", tick=0, fetch=lambda _: HTML,
             reader=reader, browser_fetch=browser)
        browser.assert_not_called()

    def test_contextual_association_is_not_publication_or_image_date_proof(self):
        reading = {"status": "review_only", "review_only": True, "words": [
            {"text": "2027", "confidence": 98, "box": [0, 0, 60, 20], "review_only": True}
        ]}
        result = {"status": "edition_identity_or_dates_unproven", "diagnostics": {
            "year_matches": True, "contradictory_dates": False, "cancellation_detected": False}}
        url = SITE + "exemple-2027.jpg"
        self.assertTrue(contextual_poster_match(SITE, url, ROW, True, reading, result))
        for bad_url in (SITE + "poster-2027.jpg", SITE + "exemple-2026.jpg",
                        SITE + "autre-2027.jpg", "https://external.fr/exemple-2027.jpg"):
            self.assertFalse(contextual_poster_match(SITE, bad_url, ROW, True, reading, result))
        self.assertFalse(contextual_poster_match(SITE, url, ROW, False, reading, result))
        for flag in ("contradictory_dates", "cancellation_detected"):
            conflict = dict(result, diagnostics=dict(result["diagnostics"], **{flag: True}))
            self.assertFalse(contextual_poster_match(SITE, url, ROW, True, reading, conflict))
        weak = dict(reading, words=[dict(reading["words"][0], confidence=40)])
        self.assertFalse(contextual_poster_match(SITE, url, ROW, True, weak, result))
        html = '<main><h1>Festival Exemple 2027</h1><p>Festival Exemple du 13 au 15 août 2027</p><img src="/exemple-2027.jpg"></main>'
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: html,
                      reader=Mock(return_value=reading))
        self.assertTrue(report["rows"][0]["exact_visible_page_dates"])
        self.assertEqual(report["contextual_edition_matches"], 1)
        self.assertEqual(report["edition_matches"], 0)
        self.assertEqual(report["rows"][0]["images"][0]["claim_types"], [])
        self.assertFalse(report["publication_authorized"])


    def test_typed_evidence_counts_are_diagnostic_only(self):
        words = []
        for y, line in enumerate(("FESTIVAL EXEMPLE", "13 au 15 août 2027",
                                   "Artistes : Alpha, New Artist", "Pass 3J : 75 €")):
            x = 20
            for token in line.split():
                width = len(token) * 10
                words.append({"text": token, "confidence": 98,
                              "box": [x, y * 40, width, 25], "review_only": True})
                x += width + 8
        reading = {"status": "review_only", "review_only": True, "words": words}
        html = '<main><h1>Festival Exemple 2027</h1><img src="/exemple-2027.jpg"></main>'
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: html,
                      reader=Mock(return_value=reading))
        self.assertEqual(report["structured_artist_count"], 2)
        self.assertEqual(report["structured_pass_count"], 1)
        self.assertEqual(report["rows"][0]["images"][0]["structured_artist_count"], 2)
        self.assertNotIn("New Artist", str(report))
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(ROW["lineup"], [])
