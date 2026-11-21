"""Adversarial offline tests: DILA-anchored source discovery, never approval."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_dynamic_municipal_source_links import (
    SCHEMA, scan_municipal_page, research_from_private_municipal_reader,
    public_redacted_summary, MAX_BATCH,
)
from ptitesondes_municipal_official_page_reader import MunicipalOfficialPageReader

CITY = "Ville-les-Bois"
HOME = "https://www.ville-les-bois.fr/"
PAGE = "https://agenda.ville-les-bois.fr/culture/jeunesse"
LICENSE = "Direction de l'information légale et administrative (Premier ministre)"


def directory(city=CITY, homepage=HOME):
    code = "12345"
    entry = {
        "nom": "Mairie - " + city,
        "categorie": "SL", "statut_de_diffusion": "true",
        "version_type": "Publiable", "copyright": LICENSE,
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid-test",
        "code_insee_commune": code,
        "pivot": json.dumps([{
            "type_service_local": "mairie", "code_insee_commune": [code]}]),
        "adresse": json.dumps([{"nom_commune": city, "pays": "France"}]),
        "site_internet": json.dumps([{"libelle": "", "valeur": homepage}]),
    }
    return {"total_count": 1, "results": [entry]}


def page(*links, url=PAGE):
    anchors = "".join(f'<a href="{target}">Programmation originale</a>'
                      for target in links)
    return {"url": url, "html":
            "<!doctype html><html><body><main><article>" + anchors
            + "</article></main></body></html>"}


class DynamicMunicipalSourceLinksTests(unittest.TestCase):
    def test_unknown_event_and_organizer_domain_is_discovered_without_registry(self):
        url = "https://culture-nouvelle-scene.fr/agenda/spectacle-jeune-public"
        report = scan_municipal_page(
            CITY, directory(), page(url))
        self.assertEqual(report["status"], "private_source_link_research_only")
        self.assertTrue(report["municipal_domain_confirmed_by_dila"])
        self.assertEqual([r["url"] for r in report["source_candidates"]], [url])
        self.assertFalse(report["candidate_domains_officially_approved"])
        self.assertFalse(report["organizers_independently_verified"])
        self.assertFalse(report["event_sessions_verified"])
        self.assertFalse(report["reuse_rights_verified"])
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["publisher_connected"])
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["discovered_destination_fetches"], 0)

    def test_any_host_and_any_wording_including_unnamed_venue(self):
        urls = [
            "https://organisateur-inedit.fr/une-experience-sonore-inconnue",
            "https://festivites-village.fr/scene-sur-la-place",
            "https://ma-nouvelle-billetterie.fr/event?id=9877",
            "https://les-mots-inventes.fr/xyz",
            "/culture/evenement/salle-sans-numero",
        ]
        report = scan_municipal_page(CITY, directory(), page(*urls))
        self.assertEqual(report["total_links_on_page"], 5)
        self.assertIn(
            "https://agenda.ville-les-bois.fr/culture/evenement/salle-sans-numero",
            [r["url"] for r in report["source_candidates"]])
        self.assertIn(urls[0], [r["url"] for r in report["source_candidates"]])

    def test_more_than_forty_sources_are_paginated_not_discarded(self):
        urls = [f"https://organizer-{i}.fr/programme" for i in range(125)]
        discovered = []
        cursor = None
        for pass_no in range(4):
            result = scan_municipal_page(
                CITY, directory(), page(*urls), cursor=cursor,
                batch_size=MAX_BATCH)
            self.assertEqual(result["status"], "private_source_link_research_only")
            discovered.extend(x["url"] for x in result["source_candidates"])
            cursor = result["next_cursor"]
            self.assertEqual(cursor is None, pass_no == 3)
        self.assertEqual(discovered, urls)
        self.assertEqual(len(set(discovered)), 125)

    def test_cursor_is_bound_to_the_page_and_cannot_skip_changed_content(self):
        result = scan_municipal_page(
            CITY, directory(), page(*[f"https://a{i}.fr/item" for i in range(60)]))
        self.assertIsNotNone(result["next_cursor"])
        tampered = dict(result["next_cursor"], next_index=9999)
        self.assertEqual(scan_municipal_page(
            CITY, directory(), page("https://new.fr/x"),
            cursor=result["next_cursor"])["status"],
            "municipal_source_cursor_mismatch")
        self.assertEqual(scan_municipal_page(
            CITY, directory(), page(*[f"https://a{i}.fr/item" for i in range(60)]),
            cursor=tampered)["status"], "municipal_source_cursor_mismatch")
        self.assertEqual(scan_municipal_page(
            CITY, directory(), page(*[f"https://a{i}.fr/item" for i in range(60)]),
            cursor=False)["status"], "municipal_source_cursor_mismatch")

    def test_municipal_origin_must_be_authenticated_independently_by_dila(self):
        target = "https://new-theatre.fr/event"
        for bad_city, dila, municipal_url in (
            ("Autre Ville", directory(), PAGE),
            (CITY, directory(city="Autre Ville"), PAGE),
            (CITY, directory(homepage="https://other-town.fr/"), PAGE),
            (CITY, {"total_count": 0, "results": []}, PAGE),
            (CITY, directory(), "https://agenda.ville-les-bois.fr.evil.fr/a"),
            (CITY, directory(), "https://evil.fr/jeunesse"),
            (CITY, directory(), "http://agenda.ville-les-bois.fr/jeunesse"),
        ):
            with self.subTest(city=bad_city, url=municipal_url):
                outcome = scan_municipal_page(
                    bad_city, dila, page(target, url=municipal_url))
                self.assertEqual(outcome["source_candidates"], [])
                self.assertFalse(outcome["municipal_domain_confirmed_by_dila"])

    def test_fake_official_claim_from_event_does_not_approve_anything(self):
        target = "https://some-organizer.fr/programme"
        officialish = page(target)
        officialish["html"] = officialish["html"].replace(
            "</article>", "<p>Officially approved by city, rights granted</p></article>")
        out = scan_municipal_page(CITY, directory(), officialish)
        self.assertEqual(out["source_candidates"][0]["url"], target)
        self.assertFalse(out["candidate_domains_officially_approved"])
        self.assertFalse(out["reuse_rights_verified"])

    def test_hidden_and_script_links_are_ignored_but_navigation_is_discovered(self):
        raw = (
            "<html><head><a href='https://head.evil.fr/a'>a</a></head>"
            "<body><nav><a href='https://nav.fr/x'>x</a></nav>"
            "<main><script><a href='https://script.fr/x'></a></script>"
            "<a style='display:none' href='https://hidden.fr/x'>h</a>"
            "<section aria-hidden='true'><a href='https://aria.fr/x'>h</a></section>"
            "<template><a href='https://template.fr/x'>h</a></template>"
            "<a href='https://real-new-scene.fr/event'>Visible</a>"
            "</main></body></html>"
        )
        result = scan_municipal_page(CITY, directory(), {"url": PAGE, "html": raw})
        self.assertEqual([x["url"] for x in result["source_candidates"]],
                         ["https://nav.fr/x",
                          "https://real-new-scene.fr/event"])

    def test_old_municipal_site_without_main_or_article_is_not_silenced(self):
        html = (
            "<html><body><div class='central-1978'>"
            "<a href='https://nouveau-conteur.fr/scene'>Sortie</a>"
            "</div></body></html>"
        )
        result = scan_municipal_page(
            CITY, directory(), {"url": PAGE, "html": html})
        self.assertEqual([x["url"] for x in result["source_candidates"]],
                         ["https://nouveau-conteur.fr/scene"])
        self.assertFalse(result["publication_ready"])

    def test_unsafe_urls_are_not_fetched_or_transferred(self):
        urls = [
            "http://untrusted.fr/", "https://127.0.0.1/",
            "https://10.0.0.1/secret", "https://localhost/admin",
            "https://fake.internal/data", "https://editor:password@example.fr/",
            "https://good.fr:8080/agenda",
            "https://good.fr.evil.invalid/agenda",
            "javascript:alert(1)", "//evil.fr/x", "ftp://other.fr/",
        ]
        safe = "https://brand-new-organizer.fr/event"
        result = scan_municipal_page(CITY, directory(), page(*urls, safe))
        self.assertEqual([x["url"] for x in result["source_candidates"]], [safe])
        self.assertEqual(result["discovered_destination_fetches"], 0)

    def test_identical_urls_deduplicated_but_different_paths_kept(self):
        first = "https://unknown-venue.fr/show1"
        second = "https://unknown-venue.fr/show2"
        result = scan_municipal_page(
            CITY, directory(), page(first, first, second))
        self.assertEqual([x["url"] for x in result["source_candidates"]],
                         [first, second])

    def test_reader_adapter_reuses_existing_private_dila_openagenda_component(self):
        reader = object.__new__(MunicipalOfficialPageReader)
        reader.official_page_get = lambda group: (
            PAGE, page("https://unlisted-organizer.fr/agenda")["html"])
        reader.dila_directory_get = lambda city: directory()
        group = {"city": CITY, "venue": "Place sans numéro", "uids": ["123"]}
        report = research_from_private_municipal_reader(group, reader)
        self.assertEqual(report["status"], "private_source_link_research_only")
        self.assertEqual(report["source_candidates_this_batch"], 1)
        reader.dila_directory_get = lambda city: directory(
            homepage="https://other-town.fr/")
        report = research_from_private_municipal_reader(group, reader)
        self.assertEqual(report["source_candidates"], [])
        self.assertEqual(report["status"], "unverified_municipal_source")
        self.assertFalse(report["publication_ready"])

    def test_public_summary_never_exposes_private_urls_or_injected_status(self):
        secret_url = "https://personal-staging-private-source.fr/events"
        result = scan_municipal_page(CITY, directory(), page(secret_url))
        public = public_redacted_summary(result)
        self.assertEqual(public["candidates_examined_in_batch"], 1)
        self.assertNotIn(secret_url, json.dumps(public))
        self.assertFalse(public["publisher_connected"])
        self.assertEqual(public["public_writes"], 0)
        with self.assertRaises(ValueError):
            public_redacted_summary(dict(
                result, status=secret_url))

    def test_oversized_html_and_url_stop_without_partial_acceptance(self):
        too_large = {"url": PAGE, "html": "<main>" + "x" * 450001 + "</main>"}
        self.assertEqual(scan_municipal_page(
            CITY, directory(), too_large)["source_candidates"], [])
        long_href = "https://new-source.fr/" + "a" * 1500
        out = scan_municipal_page(CITY, directory(), page(long_href))
        self.assertEqual(out["source_candidates"], [])


if __name__ == "__main__":
    unittest.main()
