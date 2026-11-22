"""Adversarial fixed-schema tests for access terms on pinned child pages."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_access_conditions import (
    SCHEMA, triage_html_access_conditions,
)

URL = "https://mpt.montpellier.fr/evenement/atelier-motricite"
PIN = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}
LEAD = {
    "title": "Atelier motricité",
    "city": "Montpellier",
    "venue": "Maison pour tous Marcel Pagnol",
    "date_start": "2026-11-21",
    "start_local": "09:15",
    "source_url": URL,
    "price_evidence": "ambiguous",
    "registration_evidence": "explicit_required",
}
BASE = """<html><body><main>
<h1>Atelier motricité</h1><p>Pour les enfants de 3 à 6 ans</p>
<p>Maison pour tous Marcel Pagnol, Montpellier</p>
<ul><li>21 novembre 2026 - 09:15 > 10:15</li></ul>
{access}
<h2>Autres événements</h2><p>Une autre activité gratuite pour les enfants</p>
</main></body></html>"""
DEFAULT = object()


def run(access="<p>Sur inscription | Gratuit</p><p>Carte MPT obligatoire</p>",
        *, lead=DEFAULT, url=URL, pin=PIN, html=None):
    page = {"url": url, "html": BASE.replace("{access}", access) if html is None else html}
    return triage_html_access_conditions(
        LEAD if lead is DEFAULT else lead, page, pin, "/evenement/")


class VisibleAccessConditions(unittest.TestCase):
    def test_free_session_with_mandatory_card_is_not_unconditional_free(self):
        out = run()
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["price_state"], "free_with_mandatory_membership")
        self.assertEqual(out["registration_state"], "required")
        self.assertTrue(out["mandatory_card_or_membership_claimed"])
        self.assertTrue(out["first_party_source_access_review_pending"])
        self.assertFalse(out["membership_cost_independently_verified"])
        for field in ("family_audience_independently_attested",
                      "organizer_independently_attested", "rights_reviewed",
                      "approval_granted", "publication_ready"):
            self.assertFalse(out[field])
        self.assertEqual(out["public_writes"], 0)
        private = json.dumps(out)
        for word in ("Montpellier", "09:15", "Marcel Pagnol", "/evenement/"):
            self.assertNotIn(word, private)

    def test_access_terms_with_no_card_are_classified_but_not_published(self):
        out = run("<p>Gratuit | Sans inscription</p>")
        self.assertEqual(out["price_state"], "free_disclosed")
        self.assertEqual(out["registration_state"], "explicit_not_required")
        self.assertFalse(out["first_party_source_access_review_pending"])
        self.assertFalse(out["publication_ready"])

    def test_mandatory_card_price_is_not_treated_as_event_ticket(self):
        out = run("<p>Sur inscription | Gratuit</p>"
                  "<p>Carte MPT obligatoire - tarif carte 10 €</p>")
        self.assertEqual(out["price_state"], "free_with_mandatory_membership")
        self.assertTrue(out["membership_fee_stated_on_source"])
        self.assertFalse(out["membership_cost_independently_verified"])
        self.assertTrue(out["first_party_source_access_review_pending"])

    def test_explicit_event_fee_is_not_invented_as_membership(self):
        out = run("<p>Sur inscription | Tarif 5 € par participant</p>")
        self.assertEqual(out["price_state"], "paid_disclosed")
        self.assertEqual(out["registration_state"], "required")
        self.assertFalse(out["mandatory_card_or_membership_claimed"])
        self.assertFalse(out["first_party_source_access_review_pending"])
        self.assertFalse(out["approval_granted"])

    def test_paying_without_exact_fee_remains_review(self):
        out = run("<p>Événement payant, sur inscription</p>")
        self.assertEqual(out["price_state"], "paid_amount_unknown")
        self.assertTrue(out["first_party_source_access_review_pending"])

    def test_conflicting_paid_free_and_registration_are_held(self):
        for access in (
            "<p>Gratuit</p><p>Entrée 10 euros</p>",
            "<p>Sur inscription | Sans inscription | Gratuit</p>",
            "<p>Carte obligatoire | Carte facultative | Gratuit</p>",
        ):
            with self.subTest(access=access):
                out = run(access)
                self.assertIn("conflicting", (out["price_state"],
                                              out["registration_state"]))
                self.assertTrue(out["first_party_source_access_review_pending"])
                self.assertFalse(out["publication_ready"])

    def test_optional_card_is_not_promoted_to_required(self):
        out = run("<p>Gratuit | Sans inscription</p>"
                  "<p>Carte MPT facultative</p>")
        self.assertEqual(out["price_state"], "free_disclosed")
        self.assertFalse(out["mandatory_card_or_membership_claimed"])
        self.assertFalse(out["approval_granted"])

    def test_hidden_navigation_and_related_event_are_not_access_proofs(self):
        for html in (
            BASE.replace("{access}", "<p>Informations pratiques</p>").replace(
                "</main>", '<p hidden>Gratuit | Sans inscription</p></main>'),
            BASE.replace("{access}", "<p>Informations pratiques</p>").replace(
                "<main>", '<nav>Gratuit | Sans inscription</nav><main>'),
            BASE.replace("{access}", "<p>Informations pratiques</p>"),
        ):
            with self.subTest(html=html[-70:]):
                out = run(html=html)
                self.assertEqual(out["price_state"], "unknown")
                self.assertEqual(out["registration_state"], "unknown")
                self.assertTrue(out["first_party_source_access_review_pending"])

    def test_normal_long_official_description_does_not_block_access_terms(self):
        description = "<p>" + ("Découverte et motricité, " * 42) + "</p>"
        out = run(description + "<p>Gratuit | Sur inscription</p>")
        self.assertEqual(out["reason"], "visible_first_party_access_terms_only")
        self.assertEqual(out["price_state"], "free_disclosed")
        self.assertEqual(out["registration_state"], "required")
        self.assertFalse(out["publication_ready"])

    def test_extremely_long_single_fragment_and_fragment_flood_fail_closed(self):
        gigantic = "<p>" + ("activité " * 600) + "</p>"
        out = run(gigantic + "<p>Gratuit | Sur inscription</p>")
        self.assertEqual(out["reason"], "visible_terms_limit_exceeded")
        self.assertEqual(out["price_state"], "unknown")
        self.assertFalse(out["approval_granted"])
        tiny = "".join("<span>jour</span>" for _ in range(1300))
        out = run(tiny + "<p>Gratuit | Sur inscription</p>")
        self.assertEqual(out["reason"], "visible_terms_limit_exceeded")
        self.assertFalse(out["publication_ready"])

    def test_without_valid_exact_session_no_access_is_attested(self):
        variants = [
            (dict(LEAD, source_url="https://evil.test/redirect"), URL),
            (dict(LEAD, start_local="18:15"), URL),
            (dict(LEAD, city="Nîmes"), URL),
            (LEAD, URL + "/redirect"),
        ]
        for lead, url in variants:
            with self.subTest(url=url):
                out = run(lead=lead, url=url)
                self.assertEqual(out["reason"],
                                 "unverified_exact_first_party_session")
                self.assertEqual(out["price_state"], "unknown")
                self.assertFalse(out["approval_granted"])

    def test_access_facts_do_not_prove_rights_or_family_suitability(self):
        out = run("<p>Gratuit | Sans inscription</p>")
        self.assertFalse(out["rights_reviewed"])
        self.assertFalse(out["family_audience_independently_attested"])
        self.assertFalse(out["organizer_independently_attested"])
        self.assertEqual(out["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
