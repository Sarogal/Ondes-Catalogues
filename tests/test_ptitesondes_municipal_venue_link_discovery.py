"""Offline safety tests for single-link municipal venue page discovery."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_municipal_venue_link_discovery import (
    exact_named_venue_page,
)

CITY = "Ville-les-Bois"
HOME = "https://www.ville-les-bois.fr/"
VENUE = "Maison des enfants"
TARGET = "https://www.ville-les-bois.fr/lieux/maison-des-enfants"


def directory():
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + CITY,
        "categorie": "SL", "version_type": "Publiable",
        "statut_de_diffusion": "true",
        "copyright":
            "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/"
            "occitanie/aveyron/example",
        "code_insee_commune": "12345",
        "pivot": '[{"type_service_local":"mairie","code_insee_commune":["12345"]}]',
        "adresse": '[{"nom_commune":"Ville-les-Bois","pays":"France"}]',
        "site_internet": '[{"libelle":"","valeur":"https://www.ville-les-bois.fr/"}]',
    }]}


def html(anchors):
    return "<html><main><nav>" + anchors + (
        "</nav><p>Répertoire municipal des lieux culturels et familiaux.</p>"
        "</main></html>")


class MunicipalVenueLinkTests(unittest.TestCase):
    def target(self, markup, url=HOME, dila=None):
        return exact_named_venue_page(
            VENUE, url, markup, CITY, directory() if dila is None else dila)

    def test_exact_visible_venue_link_is_one_hop(self):
        h = html('<a href="/lieux/maison-des-enfants">Maison des enfants</a>')
        self.assertEqual(self.target(h), TARGET)

    def test_accents_and_nested_visible_anchor_elements(self):
        h = html('<a href="/lieux/maison-des-enfants">'
                 'Maison des <strong>enfants</strong></a>')
        self.assertEqual(self.target(h), TARGET)

    def test_hidden_anchor_and_script_do_not_supply_evidence(self):
        for link in (
            '<script><a href="/lieux/maison-des-enfants">Maison des enfants</a></script>',
            '<a hidden href="/lieux/maison-des-enfants">Maison des enfants</a>',
            '<a aria-hidden="true" href="/lieux/maison-des-enfants">Maison des enfants</a>',
            '<div style="display:none"><a href="/lieux/maison-des-enfants">Maison des enfants</a></div>',
        ):
            with self.subTest(link=link):
                self.assertIsNone(self.target(html(link)))

    def test_unrelated_or_deceptive_links_do_not_match(self):
        for href in (
            "https://evil.invalid/lieux/maison-des-enfants",
            "https://www.ville-les-bois.fr.evil.invalid/lieu",
            "javascript:alert(1)",
            "mailto:contact@example.fr",
            "http://www.ville-les-bois.fr/lieu",
            "https://www.ville-les-bois.fr/lieu?redirect=1",
            "/lieux/maison-des-enfants#position",
        ):
            with self.subTest(href=href):
                h = html(f'<a href="{href}">Maison des enfants</a>')
                self.assertIsNone(self.target(h))

    def test_same_url_and_ambiguous_different_links_fail(self):
        h = html(f'<a href="{HOME}">Maison des enfants</a>')
        self.assertIsNone(self.target(h))
        h = html(
            '<a href="/lieux/maison-des-enfants">Maison des enfants</a>'
            '<a href="/lieux/maison-des-enfants-2">Maison des enfants</a>')
        self.assertIsNone(self.target(h))

    def test_not_exact_text_rejected(self):
        h = html('<a href="/lieux/maison-des-enfants">'
                 'Maison des enfants et des jeunes</a>')
        self.assertIsNone(self.target(h))

    def test_missing_directory_and_no_city_scope_blocks(self):
        h = html('<a href="/lieux/maison-des-enfants">Maison des enfants</a>')
        self.assertIsNone(self.target(h, dila={"total_count":0,"results":[]}))
        self.assertIsNone(exact_named_venue_page(
            VENUE, HOME, h, "Other-Ville", directory()))

    def test_no_dynamic_crawl_or_implicit_authorization(self):
        h = html('<a href="/lieux/maison-des-enfants">Maison des enfants</a>')
        url = self.target(h)
        self.assertTrue(url.startswith("https://"))
        self.assertNotIn("publication_ready", url)
        self.assertEqual(url, TARGET)


if __name__ == "__main__":
    unittest.main()
