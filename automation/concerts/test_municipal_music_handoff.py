"""Offline end-to-end tests for private Festivals -> Concerts municipal discovery."""
from copy import deepcopy
import unittest

from municipal_music_handoff import (
    SCHEMA, SOURCE, _trusted_dossiers, _recheck_event, reverify,
)
from national_municipal_pages_preflight import SCHEMA as PAGES_SCHEMA
from national_municipal_source_research import (
    SCHEMA as MUNICIPAL_SCHEMA, mairie_records_url,
)

TODAY = "2026-11-21"
SITE = "https://www.municipalite-nouvelle.fr/"
CITY = "Ville Sans Catalogue"
INSEE = "01234"
DOSSIER = "national-" + "a"*20
NAME = "GermiRock'n Co #2"
INDEX = SITE + "agenda"
DETAIL = SITE + "evenement/germirockn-co-2/"

def queue():
    return {"schema": "grossesondes.national-festival-discovery-private.v1",
            "dossiers": [{
                "id": DOSSIER, "name_hint": "Festival Inconnu 2027",
                "city_hint": CITY, "edition_year_hint": 2027,
            }]}

def municipality():
    return {"schema": MUNICIPAL_SCHEMA, "as_of": TODAY,
            "publication_authorized": False, "publications": 0,
            "review_only": True,
            "rows": [{
                "dossier_id": DOSSIER, "city_hint": CITY,
                "code_insee": INSEE,
                "status": "MUNICIPAL_WEBSITE_RESEARCH_ONLY",
                "municipal_website": SITE,
                "municipal_directory_source": mairie_records_url(INSEE),
            }]}

def clue(title=NAME, index=INDEX, detail=DETAIL,
         category="UNCLASSIFIED_MUSIC_EVENT_REVIEW_ONLY"):
    return {
        "title_hint": title,
        "index_url_review_only": index,
        "detail_url_review_only": detail,
        "classification": category,
        "review_only": True, "publication_authorized": False,
        "festival_verified": False, "concert_verified": False,
        "date_verified": False,
    }

def pages(clues=None):
    if clues is None:
        clues = [clue()]
    return {
        "schema": PAGES_SCHEMA, "as_of": TODAY,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "unknown_music_links_publications": 0,
        "rows": [{
            "dossier_id": DOSSIER, "site_rederived": True,
            "municipal_website": SITE,
            "unknown_music_links_review_only": clues,
        }],
    }

def geo(city):
    assert city == CITY
    return {"city": CITY, "codeInsee": INSEE}

def dila(url):
    assert url == mairie_records_url(INSEE)
    return {"total_count": 1, "results": [{
        "nom": "Mairie - Ville Sans Catalogue",
        "code_insee_commune": INSEE, "statut_de_diffusion": "true",
        "pivot": [{"type_service_local": "mairie",
                   "code_insee_commune": [INSEE]}],
        "site_internet": [{"valeur": SITE}],
    }]}

HOME = '<main><a href="/agenda">Agenda</a></main>'
AGENDA = (
    '<h1>Agenda municipal</h1>'
    "<a href=\"/evenement/germirockn-co-2/\">GermiRock'n Co #2</a>"
    '<a href="/evenement/punkfest/">Festival PunkFest 2027</a>'
)
ARTICLE = """<main><h1>GermiRock'n Co #2</h1>
  <p>Une soirée rock avec 4 groupes différents dans la commune.</p>
  <p>Le 27 février 2027, horaires à confirmer.</p></main>"""


class MunicipalMusicHandoffTests(unittest.TestCase):
    def test_fresh_multi_source_recheck_delivers_unknown_concert_for_private_triage(self):
        requested = []
        data = {SITE: HOME, INDEX: AGENDA, DETAIL: ARTICLE}
        def fetch(url):
            requested.append(url)
            return data[url]
        result = reverify(
            queue(), municipality(), pages(), TODAY, fetch=fetch,
            commune_lookup=geo, delegated_lookup=lambda _: self.fail(
                "Normal municipality should not need delegated lookup"),
            directory_fetch=dila)
        self.assertEqual(requested, [SITE, INDEX, DETAIL])
        self.assertEqual(result["schema"], SCHEMA)
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(result["automaticPublication"])
        self.assertEqual(result["triageCounts"], {"undated_lead": 1})
        self.assertEqual(len(result["candidates"]), 1)
        c = result["candidates"][0]
        self.assertEqual(c["source"], SOURCE)
        self.assertEqual(c["name"], NAME)
        self.assertEqual(c["sourceUrl"], DETAIL)
        self.assertEqual(c["sourcePage"], INDEX)
        self.assertEqual(c["reviewBucket"], "undated_lead")
        self.assertTrue(c["municipalMusicResearchOnly"])
        self.assertTrue(c["officialDetailFound"])
        self.assertFalse(c["sourceAuthorityVerified"])
        self.assertIsNone(c["date"])
        self.assertIsNone(c["leadArtist"])
        self.assertIsNone(c["venue"])
        self.assertIsNone(c["city"])
        self.assertEqual(c["classification"], [])
        self.assertTrue(c["reviewRequired"])
        self.assertFalse(c["publicationAllowed"])
        self.assertNotIn("officialSite", c)

    def test_forged_private_url_cannot_grant_new_network_destination(self):
        for mutated in [
            clue(detail="https://evil.example.com/concert"),
            clue(detail="https://127.0.0.1/secret"),
            clue(detail=SITE+"evenement/changed"),
            clue(index=SITE+"admin-portal"),
            clue(title="Another Rock Band"),
        ]:
            with self.subTest(mutated=mutated):
                called = []
                data = {SITE: HOME, INDEX: AGENDA}
                def fetch(url):
                    called.append(url)
                    if url not in data:
                        self.fail("A PRIVATE event URL authorized a forbidden fetch")
                    return data[url]
                out = reverify(
                    queue(), municipality(), pages([mutated]), TODAY,
                    fetch=fetch, commune_lookup=geo,
                    delegated_lookup=lambda _: None, directory_fetch=dila)
                self.assertEqual(out["candidates"], [])
                self.assertNotIn(DETAIL, called)
                self.assertFalse(out["publicationAllowed"])

    def test_changed_dila_domain_blocks_all_municipal_html_fetches(self):
        def other_dila(_url):
            data = dila(mairie_records_url(INSEE))
            data["results"][0]["site_internet"] = [
                {"valeur": "https://www.other-mairie.fr/"}]
            return data
        out = reverify(
            queue(), municipality(), pages(), TODAY,
            fetch=lambda _: self.fail("Untrusted private domain must not be visited"),
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=other_dila)
        self.assertEqual(out["candidates"], [])

    def test_festival_candidates_remain_in_festivals_not_concerts(self):
        out = reverify(
            queue(), municipality(),
            pages([clue(title="Festival PunkFest 2027",
                        detail=SITE+"evenement/punkfest/",
                        category="POSSIBLE_FESTIVAL_REVIEW_ONLY")]),
            TODAY, fetch=lambda _: self.fail("Do not fetch festival as concert"),
            commune_lookup=geo, directory_fetch=dila)
        self.assertEqual(out["candidates"], [])
        self.assertFalse(out["publicationAllowed"])

    def test_private_authorization_stale_dates_and_malformed_lists_fail_closed(self):
        cases = [
            ("pages", "publication_authorized", True),
            ("pages", "publications", 1),
            ("pages", "unknown_music_links_publications", 1),
            ("pages", "as_of", "2026-11-17"),
            ("pages", "safe_to_publish", True),
            ("municipal", "as_of", "2026-11-20"),
            ("municipal", "publication_authorized", True),
            ("municipal", "rows", "not a list"),
        ]
        for origin, field, value in cases:
            with self.subTest(field=field, origin=origin):
                m, p = municipality(), pages()
                if origin == "pages":
                    p[field] = value
                else:
                    m[field] = value
                with self.assertRaises(ValueError):
                    reverify(queue(), m, p, TODAY,
                             fetch=lambda _: self.fail("No network"))
        self.assertEqual(reverify(
            queue(), municipality(), pages(), TODAY, limit=0)["candidates"], [])
        with self.assertRaises(ValueError):
            reverify(queue(), municipality(), pages(), TODAY, limit=1000)

    def test_hidden_event_name_cannot_qualify_article(self):
        altered = ARTICLE.replace("<h1>GermiRock'n Co #2</h1>",
                                  "<h1>Concert à venir</h1>"
                                  "<div hidden>GermiRock'n Co #2</div>")
        data = {SITE: HOME, INDEX: AGENDA, DETAIL: altered}
        out = reverify(
            queue(), municipality(), pages(), TODAY,
            fetch=lambda url: data[url],
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=dila)
        self.assertEqual(out["candidates"], [])

    def test_anti_robot_gateway_must_not_count_as_event_page(self):
        shield = "<main><h1>Vérification de sécurité</h1><p>" + (
            "Secure Handler for Intelligent Enforcement & Legitimate Detection"
        ) + "</p></main>"
        for target in (SITE, INDEX, DETAIL):
            with self.subTest(target=target):
                data = {SITE: HOME, INDEX: AGENDA, DETAIL: ARTICLE}
                data[target] = shield
                out = reverify(
                    queue(), municipality(), pages(), TODAY,
                    fetch=lambda url: data[url],
                    commune_lookup=geo, delegated_lookup=lambda _: None,
                    directory_fetch=dila)
                self.assertEqual(out["candidates"], [])


if __name__ == "__main__":
    unittest.main()
