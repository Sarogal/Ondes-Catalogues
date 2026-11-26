"""Bounded national brand-domain fallback, independent of ticket provider."""
import unittest
from unittest.mock import patch, Mock

from national_brand_domain_research import (
    brand_domain_candidate, research_brand_domain,
)

TODAY = "2026-11-26"
NAME = "Festival Nocturne Sauvage 2026 - 4J PASS (4-events)"
TITLE = "Nocturne Sauvage 2026"
SITE = "https://nocturnesauvage.fr/"
LEAD = {"name_hint": NAME, "edition_year_hint": 2026, "observed_at": TODAY,
        "review_only": True, "publication_authorized": False,
        "safe_to_publish": False}


class BrandDomainResearchTests(unittest.TestCase):
    def test_bounded_single_candidate(self):
        self.assertEqual(brand_domain_candidate(NAME, 2026), (TITLE, SITE))
        for name in ("Festival Rock Metal 2026 - 4J PASS",
                     "Festival Nocturne Sauvage 2025 - 4J PASS",
                     "Nocturne Sauvage 2026", "https://example.org 2026 - 4J PASS"):
            self.assertIsNone(brand_domain_candidate(name, 2026))

    @patch("national_brand_domain_research.verify_first_party_claims")
    def test_fresh_validated_lead_and_exact_title_only(self, verify):
        fetch = Mock()
        verify.return_value = (("2026-12-01", "2026-12-05"), None)
        report = research_brand_domain(LEAD, TITLE, 2026, TODAY, fetch=fetch)
        verify.assert_called_once_with(SITE, TITLE, TODAY, fetch=fetch)
        self.assertEqual(report["status"], "FIRST_PARTY_BRAND_EDITION_REVIEW_ONLY")
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["dates_review_only"], ["2026-12-01", "2026-12-05"])
        verify.reset_mock()
        for lead in (dict(LEAD, observed_at="2026-11-25"),
                     dict(LEAD, publication_authorized=True),
                     dict(LEAD, safe_to_publish=True)):
            self.assertEqual(research_brand_domain(lead, TITLE, 2026, TODAY)["status"],
                             "NO_BRAND_DOMAIN_CANDIDATE")
        research_brand_domain(LEAD, "Unrelated Festival 2026", 2026, TODAY)
        verify.assert_not_called()

    @patch("national_brand_domain_research.verify_first_party_claims", return_value=None)
    def test_no_domain_or_dates_without_first_party_proof(self, verify):
        report = research_brand_domain(LEAD, TITLE, 2026, TODAY)
        self.assertEqual(report["status"], "BRAND_DOMAIN_OR_EDITION_UNPROVEN")
        self.assertIsNone(report["site_review_only"])
        self.assertIsNone(report["dates_review_only"])
        verify.assert_called_once()
