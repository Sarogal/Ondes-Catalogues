"""Offline, no-network regression suite for dynamic municipal page discovery."""
from copy import deepcopy
import unittest

from national_municipal_pages_preflight import (
    SCHEMA, _rederive_municipal_site, safe_same_host_article,
    _candidate_links, _visible_named_festival, scan, MAX_PAGES_PER_WEBSITE,
)
from national_municipal_source_research import (
    SCHEMA as MUNICIPAL_SCHEMA, mairie_records_url
)

TODAY = "2026-11-21"
SITE = "https://www.mairie-inconnue.fr/"
CITY = "Ville Imaginée"
INSEE = "01234"
TITLE = "Festival Foudre Libre 2027"
ID = "national-" + "a"*20

def dossier():
    return {"id": ID, "name_hint": TITLE, "city_hint": CITY,
            "edition_year_hint": 2027,
            "region_hint": "Auvergne-Rhône-Alpes",
            "publication_authorized": False}

def queue():
    return {"schema": "grossesondes.national-festival-discovery-private.v1",
            "dossiers": [dossier()]}

def municipality():
    return {
        "schema": MUNICIPAL_SCHEMA,
        "as_of": TODAY, "review_only": True,
        "publication_authorized": False, "publications": 0,
        "rows": [{
            "dossier_id": ID, "city_hint": CITY,
            "status": "MUNICIPAL_WEBSITE_RESEARCH_ONLY",
            "code_insee": INSEE,
            "municipal_directory_source": mairie_records_url(INSEE),
            "municipal_website": SITE,
        }]
    }

def mairie_doc(site=SITE):
    return {"total_count": 1, "results": [{
        "nom": "Mairie - Ville Imaginée",
        "code_insee_commune": INSEE,
        "statut_de_diffusion": "true",
        "pivot": [{"type_service_local": "mairie",
                   "code_insee_commune": [INSEE]}],
        "site_internet": [{"valeur": site}],
    }]}

def geo(name):
    if name != CITY:
        raise AssertionError("Unknown municipality")
    return {"city": CITY, "codeInsee": INSEE}

def dila(url):
    assert url == mairie_records_url(INSEE)
    return mairie_doc()

class NationalMunicipalPagesTests(unittest.TestCase):
    def test_admission_requires_fresh_independent_geo_dila(self):
        observed = municipality()["rows"][0]
        self.assertEqual(_rederive_municipal_site(
            observed, dossier(), geo, lambda city: self.fail("not delegated"),
            dila), SITE)
        for mutation, content in [
            ("municipal_website", "https://attacker.example.net/"),
            ("municipal_website", "http://www.mairie-inconnue.fr/"),
            ("municipal_directory_source", "https://attacker.example.net/"),
            ("code_insee", "99999"),
            ("city_hint", "Unrelated city"),
            ("dossier_id", "national-" + "b"*20),
            ("status", "UNKNOWN"),
        ]:
            with self.subTest(mutation=mutation):
                forged = dict(observed, **{mutation: content})
                self.assertIsNone(_rederive_municipal_site(
                    forged, dossier(), geo,
                    lambda city: self.fail("not delegated"),
                    # A *syntactically safe* but forged public HTTPS site
                    # must be rejected by independent DILA, not a local
                    # allowlist. Invalid URL/metadata cannot even fetch DILA.
                    lambda url: mairie_doc() if mutation == "municipal_website"
                    and content.startswith("https://attacker")
                    else self.fail("Malformed source cannot reach DILA")))
        self.assertIsNone(_rederive_municipal_site(
            observed, dossier(), geo,
            lambda _: self.fail("not delegated"),
            lambda _: mairie_doc("https://other-mairie.fr/")))
        self.assertIsNone(_rederive_municipal_site(
            observed, dossier(), lambda _: None,
            lambda _: None,
            lambda _: self.fail("no DILA without geo proof")))

    def test_host_bounded_navigation_refuses_encoded_traversal_or_media(self):
        safe = [
            ("/actualites", SITE + "actualites"),
            ("agenda", SITE + "agenda"),
            ("https://www.mairie-inconnue.fr/festival/edition-2027",
             SITE + "festival/edition-2027"),
        ]
        for href, expected in safe:
            self.assertEqual(
                safe_same_host_article(href, SITE, SITE), expected)
        for bad in (
            "https://evil.example.com/agenda", "//evil.example.com/news",
            "http://www.mairie-inconnue.fr/agenda",
            "https://127.0.0.1/private", "/%2e%2e/admin",
            "/../admin", "/./agenda", "/files/programmation.pdf",
            "/agenda?url=http://127.0.0.1", "/news#part",
            "javascript:alert(1)", "data:text/html,test", "\\\\evil.example",
            "/..%2Fsecret", "https://www.mairie-inconnue.fr:8080/agenda",
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(safe_same_host_article(bad, SITE, SITE))

    def test_home_news_article_finds_visible_named_mention_without_publication(self):
        root_html = """<main><h1>Site municipal</h1>
          <a href="/actualites">Actualités</a>
          <a href="https://evil.example/edition-2027">Fausse annonce</a>
          <a href="/%2e%2e/edition-2027">Traversal</a>
          <a href="/contact">Contact</a></main>"""
        news_html = """<h1>Actualités de la commune</h1>
          <a href="/actualites/foudre-libre">Festival Foudre Libre 2027</a>
          <a href="/politique">Élections</a>"""
        edition_html = """<main><h1>Festival Foudre Libre 2027</h1>
          <p>Concerts rock et métal, les 12 et 13 juin 2027, au village.</p>
          </main>"""
        pages = {
            SITE: root_html,
            SITE + "actualites": news_html,
            SITE + "actualites/foudre-libre": edition_html,
        }
        visited = []
        out = scan(
            queue(), municipality(), TODAY,
            fetch=lambda url: (visited.append(url), pages[url])[1],
            commune_lookup=geo,
            delegated_lookup=lambda _: self.fail("not delegated"),
            directory_fetch=dila)
        self.assertEqual(visited, list(pages))
        self.assertEqual(out["checked_sites"], 1)
        self.assertEqual(out["rederived_official_municipal_sites"], 1)
        # The news index links to the named article; both visible mentions
        # are PRIVATE clues, not independent corroborating sources.
        self.assertEqual(out["named_municipal_mention_count"], 2)
        row = out["rows"][0]
        self.assertEqual(row["pages_checked"], 3)
        self.assertEqual(row["status"], "NAMED_MUNICIPAL_MENTION_RESEARCH_ONLY")
        self.assertEqual(row["named_visible_pages"][-1]["url"],
                         SITE + "actualites/foudre-libre")
        self.assertTrue(row["named_visible_pages"][-1][
            "edition_year_visible_review_only"])
        self.assertTrue(row["site_rederived"])
        self.assertFalse(row["publication_authorized"])
        self.assertFalse(out["publication_authorized"])
        self.assertFalse(out["safe_to_publish"])
        self.assertEqual(out["publications"], 0)
        self.assertNotIn("startDate", str(out))
        self.assertNotIn("officialSite", str(out))

        # If DILA attribution changes, NO municipal web request may occur.
        refused = scan(
            queue(), municipality(), TODAY,
            fetch=lambda url: self.fail("Private URL cannot grant HTTP"),
            commune_lookup=geo,
            delegated_lookup=lambda _: None,
            directory_fetch=lambda url: mairie_doc(
                "https://www.another-town-hall.fr/"))
        self.assertEqual(refused["rows"][0]["status"],
                         "INDEPENDENT_MAIRIE_RECHECK_NOT_PROVEN")
        self.assertEqual(refused["rederived_official_municipal_sites"], 0)
        self.assertEqual(refused["named_municipal_mention_count"], 0)

    def test_hidden_script_only_and_unrelated_festival_never_qualifies(self):
        self.assertFalse(_visible_named_festival(
            "<script>Festival Foudre Libre 2027</script>"
            "<main>Site de mairie et agenda</main>", TITLE))
        self.assertFalse(_visible_named_festival(
            "<main>Festival de musique populaire 2027</main>", TITLE))
        self.assertTrue(_visible_named_festival(
            "<h2>Festival Foudre Libre 2027</h2>", TITLE))
        out = scan(
            queue(), municipality(), TODAY,
            fetch=lambda _: "<h1>Agenda</h1><p>Festival non identifié</p>",
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=dila)
        self.assertEqual(out["rows"][0]["status"],
                         "NO_NAMED_MUNICIPAL_MENTION")
        self.assertEqual(out["named_municipal_mention_count"], 0)

    def test_unrelated_categories_external_hosts_and_overbudget_fails_closed(self):
        html = ('<main>' + "".join(
            '<a href="/actualites/item' + str(i) +
            '">Actualités</a>' for i in range(50))
            + '<a href="https://127.0.0.1/private">Agenda</a>'
            + '<a href="/fichier.pdf">Télécharger la programmation PDF</a>'
            + '<a hidden href="/invisible-2027">Festival Foudre Libre 2027</a>'
            + '</main>')
        links = _candidate_links(html, SITE, SITE, TITLE, 2027, TODAY)
        self.assertLessEqual(len(links), 12)
        self.assertFalse(any("127.0.0.1" in x or "invisible" in x
                             or "fichier.pdf" in x for x in links))
        called = []
        result = scan(
            queue(), municipality(), TODAY,
            fetch=lambda url: called.append(url) or html,
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=dila)
        self.assertLessEqual(len(called), MAX_PAGES_PER_WEBSITE)
        self.assertEqual(len(called), MAX_PAGES_PER_WEBSITE)
        self.assertEqual(result["publications"], 0)
        self.assertEqual(result["named_municipal_mention_count"], 0)

    def test_private_report_cannot_claim_published_or_use_old_day(self):
        for key, bad in [
            ("publication_authorized", True),
            ("publications", 1),
            ("as_of", "2026-11-20"),
            ("schema", "untrusted"),
            ("rows", "not rows"),
        ]:
            with self.subTest(key=key):
                tainted = municipality()
                tainted[key] = bad
                with self.assertRaises(ValueError):
                    scan(queue(), tainted, TODAY,
                         fetch=lambda _: self.fail("No HTTP"))
        self.assertEqual(scan(queue(), municipality(), TODAY,
                              limit=0)["checked_sites"], 0)

    def test_delegated_commune_requires_a_fresh_parent_match(self):
        delegated = municipality()
        delegated["rows"][0].update(
            city_hint="Saint-Macaire-en-Mauges",
            parent_commune="Sèvremoine",
            delegated_commune="Saint-Macaire-en-Mauges",
            delegated_code_insee=INSEE,
            administrative_relation="COMMUNE_DELEGUEE_RESEARCH_ONLY")
        q = queue()
        q["dossiers"][0]["city_hint"] = "Saint-Macaire-en-Mauges"
        calls = []
        def delegated_lookup(name):
            calls.append(name)
            return {"delegated_city": name,
                    "delegated_code_insee": INSEE,
                    "codeInsee": INSEE, "city": "Sèvremoine"}
        def dila_parent(url):
            calls.append(url)
            r = mairie_doc()
            r["results"][0]["nom"] = "Mairie - Sèvremoine"
            return r
        out = scan(q, delegated, TODAY,
                   fetch=lambda _: "<h1>Agenda</h1>",
                   commune_lookup=lambda _: None,
                   delegated_lookup=delegated_lookup,
                   directory_fetch=dila_parent)
        self.assertEqual(out["rederived_official_municipal_sites"], 1)
        self.assertEqual(calls, ["Saint-Macaire-en-Mauges",
                                 mairie_records_url(INSEE)])
        delegated["rows"][0]["parent_commune"] = "Other city"
        self.assertEqual(scan(
            q, delegated, TODAY,
            fetch=lambda _: self.fail("Mismatched parent cannot trigger HTTP"),
            commune_lookup=lambda _: None,
            delegated_lookup=delegated_lookup,
            directory_fetch=dila_parent
        )["rederived_official_municipal_sites"], 0)


if __name__ == "__main__":
    unittest.main()
