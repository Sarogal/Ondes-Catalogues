"""Bounded national brand-domain fallback, independent of ticket provider."""
import unittest
from unittest.mock import patch, Mock

from national_brand_domain_research import (
    brand_domain_candidate, research_brand_domain, brand_private_proposal,
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
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args, (SITE, TITLE, TODAY))
        self.assertTrue(callable(verify.call_args.kwargs['fetch']))
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

    @patch("national_brand_domain_research.verify_first_party_claims")
    def test_proposal_rederived_and_independently_rechecked(self, verify):
        from grossesondes_first_party_direct_edition import independently_verify, PROOF_MODE
        verify.return_value = (("2026-12-01", "2026-12-05"), None)
        report = research_brand_domain(LEAD, TITLE, 2026, TODAY)
        proposal = brand_private_proposal(LEAD, TITLE, 2026, TODAY, report)
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["proofMode"], PROOF_MODE)
        self.assertEqual(proposal["startDate"], "2026-12-01")
        self.assertEqual(proposal["endDate"], "2026-12-05")
        self.assertIsNone(proposal["city"])
        self.assertIsNone(brand_private_proposal(
            LEAD, TITLE, 2026, TODAY, dict(report, site_review_only="https://another.fr/")))
        self.assertIsNone(brand_private_proposal(
            LEAD, TITLE, 2026, TODAY, dict(report, publication_authorized=True)))
        with patch("grossesondes_first_party_direct_edition.verify_first_party_claims",
                   return_value=None) as refetch:
            self.assertIsNone(independently_verify(proposal, TODAY))
            refetch.assert_called_once()
        with patch("grossesondes_first_party_direct_edition.verify_first_party_claims",
                   return_value=(("2026-12-02", "2026-12-05"), None)):
            self.assertIsNone(independently_verify(proposal, TODAY))
        with patch("grossesondes_first_party_direct_edition.verify_first_party_claims",
                   return_value=verify.return_value):
            self.assertIsNotNone(independently_verify(proposal, TODAY))

    def test_national_preflight_routes_only_fresh_qualified_brand_proposal(self):
        import national_openagenda_linked_primary_preflight as preflight
        url = "https://openagenda.com/agenda/events/example"
        source = {"dossier_id": "national-example1", "url": url,
                  "title": TITLE, "year": 2026}
        lead = dict(LEAD, source_url=url)
        report = {"schema": preflight.SCHEMA, "as_of": TODAY,
                  "review_only": True, "safe_to_publish": False,
                  "publication_authorized": False, "publications": 0,
                  "rows": [{"dossier_id": source["dossier_id"],
                            "event_ref_review_only": url,
                            "status": "OPENAGENDA_OFFICIAL_LINK_UNPROVEN",
                            "publication_authorized": False,
                            "brand_domain_research_review_only": {
                                "status": "FIRST_PARTY_BRAND_EDITION_REVIEW_ONLY",
                                "review_only": True, "publication_authorized": False,
                                "safe_to_publish": False, "site_review_only": SITE,
                                "dates_review_only": ["2026-12-01", "2026-12-05"],
                                "city_review_only": None}}]}
        with patch.object(preflight, "eligible", return_value=[source]), \
             patch.object(preflight, "validated_openagenda_leads", return_value=[lead]):
            result = preflight.stable_private_proposals({}, {}, {}, report, TODAY)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["officialSite"], SITE)
        with patch.object(preflight, "eligible", return_value=[source]), \
             patch.object(preflight, "validated_openagenda_leads", return_value=[]):
            self.assertEqual(preflight.stable_private_proposals({}, {}, {}, report, TODAY), [])

    def test_gothic_genres_are_explicit_first_party_evidence(self):
        from grossesondes_first_party_direct_edition import branded_official_site
        for genre in ("goth", "gothique", "deathrock", "cold wave", "darkwave", "post-punk"):
            html = "<h1>Festival Nocturne Sauvage</h1><p>Musique " + genre + "</p>"
            self.assertTrue(branded_official_site(SITE, TITLE, html), genre)
        self.assertFalse(branded_official_site(SITE, TITLE,
                         "<h1>Festival Nocturne Sauvage</h1><p>Musique classique</p>"))
