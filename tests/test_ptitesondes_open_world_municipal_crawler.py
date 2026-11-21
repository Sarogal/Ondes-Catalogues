"""Offline tests: municipal page queues, cursors and no editorial allowlists."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_open_world_municipal_crawler import (
    SCHEMA, crawl_private_municipal_sources, public_redacted_crawl_summary,
)
from ptitesondes_dynamic_municipal_source_links import scan_municipal_page

CITY = "Une Ville Inédite"
ROOT_URL = "https://www.une-ville-inedite.fr/"
EXT = "https://un-organisateur-inconnu.fr/spectacles"
DIRECTORY_COPYRIGHT = (
    "Direction de l'information légale et administrative (Premier ministre)")


def dila(city=CITY, site=ROOT_URL):
    code = "12345"
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + city, "categorie": "SL",
        "statut_de_diffusion": "true", "version_type": "Publiable",
        "copyright": DIRECTORY_COPYRIGHT,
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/test/uuid",
        "code_insee_commune": code,
        "pivot": json.dumps([{
            "type_service_local": "mairie",
            "code_insee_commune": [code]}]),
        "adresse": json.dumps([{"nom_commune": city, "pays": "France"}]),
        "site_internet": json.dumps([{"libelle": "", "valeur": site}]),
    }]}


def page(*links):
    return "<html><body><div>" + "".join(
        "<a href='" + target + "'>Lien visible</a>" for target in links
    ) + "</div></body></html>"


def run(state=None, pages=None, *, page_budget=1, directory=None):
    pages = pages or {ROOT_URL: page("/culture/", EXT),
                      ROOT_URL + "culture/": page("jeunesse/"),
                      ROOT_URL + "culture/jeunesse/":
                          page("https://sortie-originale.fr/programmation")}
    return crawl_private_municipal_sources(
        CITY, state, directory_reader=lambda city: (
            dila() if directory is None else directory),
        html_reader=lambda url: pages[url], page_budget=page_budget)


class MunicipalCrawlerTests(unittest.TestCase):
    def test_unlisted_municipal_subpages_are_followed_until_exhaustion(self):
        state, found, page_batches = None, [], 0
        for idx in range(8):
            result = run(state)
            state = result["private_state"]
            found.extend(x["url"]
                         for x in result["private_external_source_links"])
            page_batches += result["page_batches_examined"]
            if result["status"] == "municipal_research_frontier_exhausted":
                break
        else:
            self.fail("frontier should be exhausted")
        self.assertEqual(page_batches, 3)
        self.assertEqual(set(found), {
            EXT, "https://sortie-originale.fr/programmation"})
        self.assertEqual(result["pages_remaining_incomplete"], 0)
        self.assertEqual(len(state["completed_pages"]), 3)
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)

    def test_more_than_forty_links_on_one_page_are_not_dropped(self):
        hrefs = [f"https://new-{i}.fr/recherche" for i in range(85)]
        pages = {ROOT_URL: page(*hrefs)}
        state, seen = None, []
        for _ in range(5):
            result = run(state, pages)
            seen.extend(x["url"]
                        for x in result["private_external_source_links"])
            state = result["private_state"]
            if result["status"] == "municipal_research_frontier_exhausted":
                break
        self.assertEqual(seen, hrefs)
        self.assertEqual(len(state["completed_pages"]), 1)
        self.assertEqual(result["page_batches_examined"], 1)

    def test_page_change_between_cursor_batches_rescans_instead_of_skip(self):
        initial = [f"https://a{i}.fr/event" for i in range(60)]
        first = run(None, {ROOT_URL: page(*initial)})
        self.assertIsNotNone(
            first["private_state"]["pending_pages"][0]["cursor"])
        modified = [f"https://brand-new{i}.fr/event" for i in range(60)]
        retry = run(first["private_state"], {ROOT_URL: page(*modified)})
        self.assertEqual(retry["page_batches_examined"], 0)
        self.assertEqual(retry["pages_remaining_incomplete"], 1)
        self.assertIsNone(
            retry["private_state"]["pending_pages"][0]["cursor"])
        replay = run(retry["private_state"],
                     {ROOT_URL: page(*modified)})
        self.assertEqual(replay["page_batches_examined"], 1)
        self.assertEqual(replay["private_external_source_links"][0]["url"],
                         modified[0])

    def test_unavailable_page_is_held_then_automatically_retried_later(self):
        def fail(url):
            raise OSError("temporary host outage")
        state = None
        for _ in range(3):
            res = crawl_private_municipal_sources(
                CITY, state, directory_reader=lambda city: dila(),
                html_reader=fail, page_budget=1)
            state = res["private_state"]
        self.assertEqual(res["status"],
                         "municipal_research_incomplete_held_pages")
        self.assertEqual(len(state["held_pages"]), 1)
        recovered = run(state, {ROOT_URL: page(EXT)})
        self.assertEqual(recovered["status"],
                         "municipal_research_frontier_exhausted")
        self.assertEqual([x["url"]
                          for x in recovered["private_external_source_links"]],
                         [EXT])
        self.assertEqual(recovered["pages_remaining_incomplete"], 0)

    def test_malicious_checkpoint_cannot_fetch_unverified_domain(self):
        state = run(None, {ROOT_URL: page(EXT)})["private_state"]
        def bad(url):
            raise AssertionError("reader must not be called")
        checks = []
        wrong = deepcopy(state)
        wrong["pending_pages"].append({
            "url": "https://evil.fr/private",
            "cursor": None, "attempts": 0})
        checks.append(wrong)
        wrong = deepcopy(state)
        wrong["completed_pages"] = ["https://evil.fr/data"]
        checks.append(wrong)
        wrong = deepcopy(state)
        wrong["dila_homepage_hosts"] = ["evil.fr"]
        checks.append(wrong)
        wrong = deepcopy(state)
        wrong["city"] = "Another town"
        checks.append(wrong)
        for item in checks:
            with self.subTest(item=item):
                res = crawl_private_municipal_sources(
                    CITY, item, directory_reader=lambda city: dila(),
                    html_reader=bad)
                self.assertEqual(res["status"],
                                 "checkpoint_or_authority_mismatch")
        self.assertEqual(len(checks), 4)

    def test_new_official_domain_is_revalidated_at_each_resume(self):
        state = run(None, {ROOT_URL: page(EXT)})["private_state"]
        changed = dila(site="https://other-municipal-site.fr/")
        out = run(state, {ROOT_URL: page(EXT)}, directory=changed)
        self.assertEqual(out["status"], "checkpoint_or_authority_mismatch")
        self.assertFalse(out["publication_ready"])

    def test_municipal_page_link_to_unusual_venue_without_postal_number(self):
        pages = {
            ROOT_URL: page("culture/"),
            ROOT_URL + "culture/": page("places/spectacle-a-la-place/"),
            ROOT_URL + "culture/places/spectacle-a-la-place/": page(EXT),
        }
        state = None
        for _ in range(10):
            out = run(state, pages)
            state = out["private_state"]
            if out["status"] == "municipal_research_frontier_exhausted":
                break
        self.assertEqual(len(state["completed_pages"]), 3)
        self.assertFalse(out["event_sessions_verified"])
        self.assertIn(EXT, [x["url"]
                            for x in out["private_external_source_links"]])

    def test_no_list_of_musical_or_artistic_words_at_discovery(self):
        result = run(None, {
            ROOT_URL: page(
                "https://inconnu.fr/concept-radiophonique-nouveau",
                "https://inconnu.fr/quelque-chose-d-inventif")})
        self.assertEqual(
            len(result["private_external_source_links"]), 2)
        self.assertFalse(result["source_reuse_rights_verified"])

    def test_public_aggregate_does_not_leak_any_links_or_city(self):
        res = run(None, {ROOT_URL: page(EXT)})
        doc = json.dumps(public_redacted_crawl_summary(res))
        for secret in (ROOT_URL, CITY, EXT):
            self.assertNotIn(secret, doc)
        fake = dict(res, publisher_connected=True)
        with self.assertRaises(ValueError):
            public_redacted_crawl_summary(fake)

    def test_empty_dila_does_not_reject_unlisted_city_permanently(self):
        out = run(directory={"total_count": 0, "results": []})
        self.assertEqual(out["status"], "municipal_domain_not_proven_at_dila")
        self.assertEqual(out["pages_fully_examined"], 0)
        self.assertFalse(out["approval_granted"])


if __name__ == "__main__":
    unittest.main()
