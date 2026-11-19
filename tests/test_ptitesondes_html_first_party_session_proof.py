"""Adversarial synthetic tests: first-party HTML is not an independent approval."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_first_party_session_proof import (
    SCHEMA, corroborate_first_party_session,
)

SOURCE = "https://mpt.montpellier.fr/evenement/atelier-yoga-enfants"
PIN = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}
LEAD = {
    "title": "Atelier yoga enfants",
    "city": "Montpellier",
    "venue": "Maison pour tous Albert Camus",
    "date_start": "2026-11-21",
    "start_local": "09:15",
    "source_url": SOURCE,
    "price_evidence": "explicit_free",
    "registration_evidence": "explicit_required",
}
PAGE = """<html><body><main>
<h1>Atelier yoga enfants</h1>
<p>Pour les enfants de 2 à 6 ans</p>
<p>Maison pour tous Albert Camus, 34070 Montpellier</p>
<ul><li>21 novembre 2026 - 09:15 > 10:15</li>
<li>21 novembre 2026 - 10:30 > 11:30</li></ul>
<p>Sur inscription, gratuit</p>
</main></body></html>"""


def check(lead=None, html=PAGE, pin=PIN, url=SOURCE):
    return corroborate_first_party_session(
        LEAD if lead is None else lead,
        {"url": url, "html": html},
        pin, "/evenement/",
    )


class FirstPartyHTMLSessionProof(unittest.TestCase):
    def test_visible_same_block_all_source_cues_without_admission(self):
        out = check()
        self.assertEqual(out["schema"], SCHEMA)
        self.assertTrue(out["visible_exact_session"])
        self.assertTrue(out["source_identity_consistent"])
        self.assertTrue(out["family_audience_source_cues_present"])
        self.assertTrue(out["access_claims_consistent"])
        self.assertFalse(out["access_needs_review"])
        self.assertEqual(out["status"], "first_party_visible_session_all_cues")
        for key in ("independent_organizer_verified",
                    "independent_venue_gps_verified",
                    "rights_reviewed", "publication_ready", "approval_granted"):
            self.assertFalse(out[key])
        self.assertTrue(out["source_is_not_independent_corroboration"])
        self.assertEqual(out["public_writes"], 0)
        result = json.dumps(out)
        for secret in ("Atelier yoga", "Montpellier", "/evenement", "09:15", "Albert Camus"):
            self.assertNotIn(secret, result)

    def test_date_and_clock_in_separate_blocks_are_held(self):
        html = PAGE.replace(
            "<li>21 novembre 2026 - 09:15 > 10:15</li>",
            "<li>21 novembre 2026</li><li>09:15 > 10:15</li>")
        out = check(html=html)
        self.assertEqual(out["status"], "same_block_date_and_clock_not_visible")
        self.assertFalse(out["visible_exact_session"])

    def test_hidden_pair_does_not_count_as_evidence(self):
        html = PAGE.replace(
            "<li>21 novembre 2026 - 09:15 > 10:15</li>",
            '<li aria-hidden="true">21 novembre 2026 - 09:15 > 10:15</li>')
        out = check(html=html)
        self.assertFalse(out["visible_exact_session"])

    def test_pinned_host_exact_url_and_child_prefix_are_not_candidate_claims(self):
        cases = (
            (LEAD, dict(PIN, approved_host="mpt.montpellier.fr.attacker.test"), SOURCE),
            (LEAD, PIN, SOURCE + "/redirection"),
            (dict(LEAD, source_url="https://mpt.montpellier.fr.attacker.test/evenement/a"),
             PIN, "https://mpt.montpellier.fr.attacker.test/evenement/a"),
            (dict(LEAD, source_url="https://mpt.montpellier.fr/actualites/a"),
             PIN, "https://mpt.montpellier.fr/actualites/a"),
        )
        for lead, pin, url in cases:
            with self.subTest(url=url):
                out = check(lead=lead, pin=pin, url=url)
                self.assertFalse(out["visible_exact_session"])
                self.assertFalse(out["approval_granted"])

    def test_title_city_clock_status_and_adult_safety_hold(self):
        for html in (
            PAGE.replace("Atelier yoga enfants", "Autre animation"),
            PAGE.replace("Montpellier", "Nîmes"),
            PAGE.replace("09:15", "08:15"),
            PAGE.replace("</main>", "<p>Événement annulé</p></main>"),
        ):
            with self.subTest(html=html[-80:]):
                out = check(html=html)
                self.assertFalse(out["visible_exact_session"])
                self.assertFalse(out["publication_ready"])

    def test_not_stated_access_is_not_approved_as_free(self):
        lead = dict(LEAD, price_evidence="not_stated",
                    registration_evidence="not_stated")
        out = check(lead=lead)
        self.assertTrue(out["visible_exact_session"])
        self.assertTrue(out["access_claims_consistent"])
        self.assertTrue(out["access_needs_review"])

    def test_ambiguous_card_price_and_missing_audience_remain_held(self):
        lead = dict(LEAD, price_evidence="ambiguous")
        html = PAGE.replace("Pour les enfants de 2 à 6 ans",
                            "Information complémentaire")
        out = check(lead=lead, html=html)
        self.assertTrue(out["visible_exact_session"])
        self.assertFalse(out["family_audience_source_cues_present"])
        self.assertFalse(out["access_claims_consistent"])
        self.assertTrue(out["access_needs_review"])
        self.assertFalse(out["approval_granted"])

    def test_explicit_access_claim_must_be_visible(self):
        html = PAGE.replace("Sur inscription, gratuit", "Informations pratiques")
        out = check(html=html)
        self.assertTrue(out["visible_exact_session"])
        self.assertFalse(out["access_claims_consistent"])
        self.assertTrue(out["access_needs_review"])

    def test_malformed_input_fails_without_private_data(self):
        for bad in (None, {}, [], "injected", dict(LEAD, start_local="30:99"),
                    dict(LEAD, title=None)):
            with self.subTest(bad=type(bad).__name__):
                out = check(lead=bad)
                self.assertFalse(out["visible_exact_session"])
                self.assertEqual(out["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
