import unittest
from unittest.mock import patch

from radio_daily_live_logo_preview import preview_logo
from radio_daily_v9_generator import digest, encode
from test_radio_daily_logo_plan import DATA, OLD, DAY, SID, PAGE, BODY, URL
import test_radio_daily_logo_release_validation as fixture_module


class LiveLogoPreviewTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.IndependentLogoGateTests()
        fixture.prepare(approved=False)
        self.fixture = fixture

    def run_preview(self):
        f = self.fixture
        return preview_logo(f.pointer, f.raw, anchor=f.anchor, day=DAY,
                            logo_maintenance=f.lm, missing_logo=f.nm)

    @patch("radio_daily_live_evidence.fetch_strict_https", return_value=(DATA, "image/png"))
    @patch("radio_daily_live_evidence.fetch_html", return_value=(PAGE, BODY))
    def test_exact_fresh_logo_reaches_independent_gate(self, page, image):
        result = self.run_preview()
        self.assertEqual(result["outcome"], "strict_gate_validated")
        self.assertEqual(result["candidateSha256"], digest(encode(self.fixture.new)))
        self.assertEqual(result["objectCount"], 1)
        self.assertEqual(result["networkCalls"], 2)
        self.assertNotIn(URL, str(result))

    @patch("radio_daily_live_evidence.fetch_strict_https", return_value=(OLD, "image/png"))
    @patch("radio_daily_live_evidence.fetch_html", return_value=(PAGE, BODY))
    def test_changed_artwork_is_deferred(self, page, image):
        result = self.run_preview()
        self.assertEqual(result["outcome"], "live_evidence_deferred")
        self.assertEqual(result["deferredCount"], 1)
        self.assertIsNone(result["candidateSha256"])

    @patch("radio_daily_live_evidence.fetch_strict_https")
    @patch("radio_daily_live_evidence.fetch_html", side_effect=OSError("network down"))
    def test_official_page_failure_does_not_authorize_logo(self, page, image):
        result = self.run_preview()
        self.assertEqual(result["outcome"], "live_evidence_deferred")
        self.assertEqual(result["networkCalls"], 1)
        image.assert_not_called()

    @patch("radio_daily_live_evidence.fetch_strict_https", return_value=(DATA, "image/png"))
    @patch("radio_daily_live_evidence.fetch_html", return_value=(PAGE, BODY+b" "))
    def test_changed_page_held_before_image(self, page, image):
        self.assertEqual(self.run_preview()["outcome"], "live_evidence_deferred")
        image.assert_not_called()

    @patch("radio_daily_live_evidence.fetch_html")
    @patch("radio_daily_live_logo_preview.plan", return_value=([], []))
    def test_no_proposal_never_fetches(self, plan, page):
        result = self.run_preview()
        self.assertEqual(result["outcome"], "no_proposal")
        self.assertEqual(result["networkCalls"], 0)
        page.assert_not_called()
