"""Adversarial offline checks for first-party public and age claims."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_family_age import SCHEMA, triage_html_family_age

URL = "https://mpt.montpellier.fr/evenement/atelier-decouverte"
PIN = {"approved_host": "mpt.montpellier.fr",
       "exact_index_url": "https://mpt.montpellier.fr/evenements"}
LEAD = {
    "title": "Atelier découverte", "city": "Montpellier",
    "venue": "Maison pour tous Albert Camus", "date_start": "2026-11-21",
    "start_local": "09:15", "source_url": URL,
    "price_evidence": "explicit_free",
    "registration_evidence": "explicit_required",
}
PAGE = """<html><body><main>
<h1>Atelier découverte</h1>
<p>Maison pour tous Albert Camus, Montpellier</p>
<ul><li>21 novembre 2026 - 09:15 > 10:15</li></ul>
{audience}
<p>Gratuit - sur inscription</p>
<h2>Autres événements</h2><p>Enfants de 3 à 6 ans</p>
</main></body></html>"""


def review(audience, lead=None, page=None):
    html = PAGE.replace("{audience}", audience) if page is None else page
    return triage_html_family_age(
        LEAD if lead is None else lead, {"url": URL, "html": html},
        PIN, "/evenement/")


class FamilyAgeEvidenceTests(unittest.TestCase):
    def assert_hold(self, out):
        self.assertFalse(out["explicit_first_party_family_audience"])
        self.assertTrue(out["family_or_age_review_pending"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted"])
        self.assertEqual(out["public_writes"], 0)

    def test_explicit_family_with_no_age_is_valid_without_inventing_age(self):
        out = review("<p>Public : Familles</p>")
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["audience_state"], "explicit_family")
        self.assertEqual(out["age_state"], "not_stated")
        self.assertIsNone(out["age_min"])
        self.assertIsNone(out["age_max"])
        self.assertFalse(out["family_or_age_review_pending"])

    def test_precise_child_age_range_is_only_claimed_as_written(self):
        out = review("<p>Pour les enfants de 3 à 6 ans</p>")
        self.assertEqual(out["audience_state"], "explicit_children")
        self.assertEqual(out["age_state"], "explicit_range")
        self.assertEqual((out["age_min"], out["age_max"]), (3, 6))

    def test_minimum_only_does_not_invent_a_maximum(self):
        out = review("<p>À partir de 6 ans</p>")
        self.assertEqual(out["audience_state"], "explicit_children")
        self.assertEqual(out["age_state"], "explicit_minimum")
        self.assertEqual(out["age_min"], 6)
        self.assertIsNone(out["age_max"])

    def test_family_cues_children_babies_teenagers(self):
        cases = (
            ("<p>Pour les bébés</p>", "explicit_children"),
            ("<p>Public : adolescents</p>", "explicit_children"),
            ("<p>Pour toute la famille</p>", "explicit_family"),
            ("<p>Familles</p>", "explicit_family"),
            ("<p>Jeune public</p>", "explicit_family"),
            ("<p>Tout public</p>", "explicit_family"),
        )
        for html, state in cases:
            with self.subTest(html=html):
                self.assertEqual(review(html)["audience_state"], state)

    def test_mixed_children_and_adults_are_included(self):
        for claim in ("<p>Atelier parents enfants</p>",
                      "<p>Enfants et adultes</p>",
                      "<p>Petits et grands</p>"):
            with self.subTest(claim=claim):
                out = review(claim)
                self.assertEqual(out["audience_state"], "explicit_mixed")
                self.assertFalse(out["family_or_age_review_pending"])

    def test_ages_spanning_childhood_and_adulthood_are_not_excluded(self):
        out = review("<p>Public de 7 à 77 ans</p>")
        self.assertEqual(out["audience_state"], "explicit_children")
        self.assertEqual((out["age_min"], out["age_max"]), (7, 77))
        self.assertFalse(out["publication_ready"])

    def test_descriptive_child_reference_is_not_an_admission_statement(self):
        for description in (
            "<p>Une conférence sur la vie des enfants au Moyen Âge</p>",
            "<p>Un livre évoquant les familles et leurs souvenirs</p>",
            "<p>La peinture représente plusieurs bébés</p>",
            "<p>Histoire des enfants de 3 à 6 ans</p>",
        ):
            with self.subTest(description=description):
                self.assert_hold(review(description))

    def test_parent_only_is_not_a_child_outing(self):
        self.assert_hold(review("<p>Pour les parents d'enfants de 3 à 6 ans</p>"))

    def test_explicit_adult_only_or_minimum_18_never_passes(self):
        for claim in (
            "<p>Adultes uniquement</p>",
            "<p>Réservé aux adultes</p>",
            "<p>Mineurs non admis</p>",
            "<p>À partir de 18 ans</p>",
            "<p>Enfants interdits</p>",
        ):
            with self.subTest(claim=claim):
                self.assert_hold(review(claim))

    def test_conflicting_family_and_adult_limit_is_held(self):
        for claim in (
            "<p>Pour toute la famille</p><p>À partir de 18 ans</p>",
            "<p>Enfants et adultes</p><p>Sans enfants</p>",
            "<p>Pour les enfants de 3 à 6 ans</p><p>Adultes uniquement</p>",
        ):
            with self.subTest(claim=claim):
                out = review(claim)
                self.assert_hold(out)

    def test_conflicting_ranges_never_generate_a_fake_age(self):
        out = review("<p>Public de 3 à 6 ans</p><p>Public de 5 à 8 ans</p>")
        self.assertEqual(out["age_state"], "conflicting")
        self.assertIsNone(out["age_min"])
        self.assertIsNone(out["age_max"])
        self.assertTrue(out["family_or_age_review_pending"])

    def test_hidden_nav_and_related_content_do_not_count(self):
        for page in (
            PAGE.replace("{audience}", '<p hidden>Public : Familles</p>'),
            PAGE.replace("{audience}", '<div aria-hidden="true">Pour les enfants</div>'),
            PAGE.replace("{audience}", '<p>Informations pratiques</p>').replace(
                "<main>", "<nav>Public : Familles</nav><main>"),
            PAGE.replace("{audience}", '<p>Informations pratiques</p>'),
        ):
            with self.subTest(page=page[-70:]):
                self.assert_hold(review("", page=page))

    def test_no_exact_time_or_source_identity_cannot_be_attested(self):
        for lead in (
            dict(LEAD, start_local="17:00"),
            dict(LEAD, city="Nîmes"),
            dict(LEAD, source_url="https://evil.example/evenement/atelier-decouverte"),
        ):
            with self.subTest(lead=lead):
                out = review("<p>Public : enfants</p>", lead=lead)
                self.assertEqual(out["reason"], "exact_first_party_session_not_verified")
                self.assert_hold(out)

    def test_large_visible_text_is_bounded_fail_closed(self):
        huge = "<p>" + "famille " * 700 + "</p><p>Public : familles</p>"
        out = review(huge)
        self.assertEqual(out["reason"], "visible_family_terms_limit_exceeded")
        self.assert_hold(out)

    def test_no_private_information_and_no_publisher_privileges(self):
        out = review("<p>Pour les enfants de 3 à 6 ans</p>")
        for key in ("organizer_independently_attested",
                    "venue_gps_independently_attested", "rights_reviewed",
                    "approval_granted", "publication_ready"):
            self.assertFalse(out[key])
        serialized = json.dumps(out)
        for private in ("Montpellier", "09:15", "Albert Camus", "/evenement/",
                        "Atelier découverte"):
            self.assertNotIn(private, serialized)


if __name__ == "__main__":
    unittest.main()
