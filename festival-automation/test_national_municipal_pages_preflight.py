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

    def test_unknown_music_not_starved_by_large_municipal_admin_menu(self):
        """Dynamic agenda priority, without a closed city/domain/event list."""
        from national_municipal_pages_preflight import _candidate_links
        homepage = (
            "<main>" + "".join(
                '<a href="/actualites/demarche-' + str(i) +
                '">Actualités administratives</a>' for i in range(65))
            + '<a href="/agenda-2/">Agenda</a>'
            + '<a href="/associations/manifestations">Manifestations</a>'
            + "</main>"
        )
        agenda = """<main><h1>Agenda des événements</h1>
          <a href="/evenement/germirockn-co-2/">GermiRock'n Co #2</a>
          </main>"""
        first = _candidate_links(
            homepage, SITE, SITE, TITLE, 2027, TODAY)
        self.assertTrue(first)
        self.assertEqual(first[0], SITE + "agenda-2/")
        # The same priority works independently for an entirely different
        # city, unseen artist, and arbitrary municipal HTTPS domain.
        visited = []
        def fetch(url):
            visited.append(url)
            return {
                SITE: homepage, SITE + "agenda-2/": agenda
            }.get(url, "<main><h1>Page d'actualités</h1></main>")
        result = scan(queue(), municipality(), TODAY,
                      fetch=fetch, commune_lookup=geo,
                      delegated_lookup=lambda _: None, directory_fetch=dila)
        self.assertGreaterEqual(len(visited), 2)
        self.assertEqual(visited[:2], [SITE, SITE + "agenda-2/"])
        self.assertEqual(result["unknown_music_links_count"], 1)
        self.assertEqual(
            result["rows"][0]["unknown_music_links_review_only"][0]["title_hint"],
            "GermiRock'n Co #2")
        self.assertFalse(result["publication_authorized"])
        self.assertEqual(result["publications"], 0)

    def test_daily_generic_rotation_preserves_priority(self):
        from national_municipal_pages_preflight import _candidate_links
        html = (
            '<a href="/agenda">Agenda</a>'
            + "".join(
                '<a href="/actualites/post-' + str(i) +
                '">Actualités</a>' for i in range(20))
        )
        one = _candidate_links(html, SITE, SITE, TITLE, 2027, "2026-11-21")
        next_day = _candidate_links(html, SITE, SITE, TITLE, 2027, "2026-11-22")
        self.assertEqual(one[0], SITE + "agenda")
        self.assertEqual(next_day[0], SITE + "agenda")
        # A changing menu rotation covers more sources instead of pinning
        # the same first three entries forever.
        self.assertNotEqual(one[1:4], next_day[1:4])
        self.assertLessEqual(len(one), 12)
        self.assertLessEqual(len(next_day), 12)

    def test_unknown_brand_without_rock_metal_or_fest_kept_for_research(self):
        """No closed genre-token requirement for a genuinely NEW festival."""
        from national_municipal_pages_preflight import (
            untyped_municipal_event_links, unknown_municipal_music_links)
        agenda = """<main><h1>Agenda communal</h1>
          <a href="/evenement/le-gros-tonneau-2027/">Le Gros Tonneau 2027</a>
          <a href="/evenement/les-gueules-de-bois/">Les Gueules de Bois</a>
          <a href="/evenement/atelier-couture/">Atelier de couture</a>
          <a href="/evenement/helixfest-2027/">HelixFest 2027</a>
          <a href="/evenement/festival-rock-2027/">Festival Rock 2027</a>
          <a href="https://evil.example/secret">Le Festival de l'ombre</a>
          <a hidden href="/evenement/crochet-cache/">Concert caché 2027</a>
          <script><a href="/evenement/faux">Le Gros Faux Festival</a></script>
          </main>"""
        typed = unknown_municipal_music_links(agenda, SITE+"agenda", SITE)
        typed_urls = {x["detail_url_review_only"] for x in typed}
        self.assertEqual(len(typed_urls), 2)
        untyped = untyped_municipal_event_links(
            agenda, SITE+"agenda", SITE, TODAY, music_urls=typed_urls)
        self.assertEqual({x["title_hint"] for x in untyped},
                         {"Le Gros Tonneau 2027", "Les Gueules de Bois",
                          "Atelier de couture"})
        for x in untyped:
            self.assertEqual(
                x["classification"],
                "UNCLASSIFIED_MUNICIPAL_EVENT_RESEARCH_ONLY")
            self.assertFalse(x["music_verified"])
            self.assertFalse(x["festival_verified"])
            self.assertFalse(x["concert_verified"])
            self.assertFalse(x["date_verified"])
            self.assertFalse(x["publication_authorized"])
            self.assertNotIn("startDate", x)
            self.assertNotIn("officialSite", x)

    def test_untyped_event_route_is_discovery_not_authorization(self):
        from national_municipal_pages_preflight import untyped_municipal_event_links
        index = """<h1>Agenda</h1>
          <a href="/evenement/nouvelle-scene-2027/">La Nouvelle Scène</a>
          <a href="/demarches/manifestation/">Organiser une manifestation</a>
          <a href="/actualites/mairie/">Actualités de la mairie</a>
          <a href="http://evil.example/evenement/faux/">Le Faux Festival</a>
          <a href="/evenement/%2e%2e/private/">Ceci est invalide</a>
          """
        h = '<a href="/agenda">Agenda</a>'
        pages = {SITE: h, SITE+"agenda": index}
        seen = []
        def fetch(url):
            seen.append(url)
            return pages.get(url, "<main><h1>Actualités</h1></main>")
        result = scan(
            queue(), municipality(), TODAY, fetch=fetch,
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=dila)
        self.assertEqual(seen[:2], [SITE, SITE+"agenda"])
        self.assertEqual(result["unknown_music_links_count"], 0)
        self.assertEqual(result["untyped_event_links_count"], 1)
        self.assertEqual(result["untyped_event_links_publications"], 0)
        self.assertEqual(
            result["rows"][0]["untyped_event_links_review_only"][0]["title_hint"],
            "La Nouvelle Scène")
        self.assertFalse(result["publication_authorized"])
        self.assertEqual(result["publications"], 0)
        self.assertEqual(untyped_municipal_event_links(
            '<a href="https://evil.example/evenement/foo/">Un événement</a>',
            SITE, SITE, TODAY), [])

    def test_untyped_day_rotation_does_not_favour_first_twelve_ever(self):
        from national_municipal_pages_preflight import (
            untyped_municipal_event_links, MAX_UNTYPED_EVENT_LINKS)
        html = "".join(
            '<a href="/evenement/inconnu-' + str(i) +
            '/">Le Rendez Vous ' + str(i) + '</a>'
            for i in range(40))
        a = untyped_municipal_event_links(html, SITE, SITE, "2026-11-21")
        b = untyped_municipal_event_links(html, SITE, SITE, "2026-11-22")
        self.assertEqual(len(a), MAX_UNTYPED_EVENT_LINKS)
        self.assertEqual(len(b), MAX_UNTYPED_EVENT_LINKS)
        self.assertNotEqual(
            [x["detail_url_review_only"] for x in a],
            [x["detail_url_review_only"] for x in b])
        self.assertTrue(all(x["publication_authorized"] is False for x in a+b))

    def test_security_challenge_is_unavailable_not_negative_evidence(self):
        # Real municipal administrations may use anti-bot gateways. They
        # cannot be bypassed and must not count as no festival scheduled.
        html = """<html><head><title>S.H.I.E.L.D.</title></head>
          <main><h1>Vérification de sécurité</h1>
          <p>Secure Handler for Intelligent Enforcement & Legitimate Detection</p>
          <p>Vérifie que votre navigateur est légitime.</p>
          </main></html>"""
        observed = []
        out = scan(
            queue(), municipality(), TODAY,
            fetch=lambda url: observed.append(url) or html,
            commune_lookup=geo, delegated_lookup=lambda _: None,
            directory_fetch=dila)
        self.assertEqual(observed, [SITE])
        row = out["rows"][0]
        self.assertEqual(row["access_challenge_pages"], 1)
        self.assertEqual(row["pages_checked"], 1)
        self.assertEqual(row["status"],
                         "MUNICIPAL_ACCESS_CHALLENGE_RESEARCH_UNAVAILABLE")
        self.assertEqual(out["named_municipal_mention_count"], 0)
        self.assertFalse(out["publication_authorized"])
        self.assertEqual(out["publications"], 0)

    def test_unlisted_music_event_names_from_municipal_agenda_are_retained(self):
        """One official agenda can nominate NEW festival, concert and unknown music.

        No artist, site, municipal URL or festival name is hard-coded as an
        acceptance rule. It only classifies unverified research clues.
        """
        from national_municipal_pages_preflight import unknown_municipal_music_links
        index = """<main><h1>Agenda de la ville</h1>
          <a href="/evenement/germirockn-co-2/">GermiRock'n Co #2</a>
          <a href="/evenement/meteorite/">Festival Météorite Noire 2027</a>
          <a href="/evenement/concert-des-ombres/">Concert des Ombres Punk</a>
          <a href="/evenement/accueil-famille/">Accueil des familles</a>
          <a href="/evenement/atelier/">Atelier de couture</a>
          <a href="/evenement/annonce">Lire la suite</a>
          <a href="https://127.0.0.1/secret">Festival Métal privé</a>
          <a hidden href="/evenement/faux-festival/">Festival Metal Fake 2027</a>
          <script><a href="/evenement/fake">Festival Metal 2027</a></script>
          </main>"""
        clues = unknown_municipal_music_links(index, SITE+"agenda", SITE)
        titles = {x["title_hint"]: x for x in clues}
        self.assertEqual(set(titles), {
            "GermiRock'n Co #2", "Festival Météorite Noire 2027",
            "Concert des Ombres Punk",
        })
        self.assertEqual(
            titles["GermiRock'n Co #2"]["classification"],
            "UNCLASSIFIED_MUSIC_EVENT_REVIEW_ONLY")
        self.assertEqual(
            titles["Festival Météorite Noire 2027"]["classification"],
            "POSSIBLE_FESTIVAL_REVIEW_ONLY")
        self.assertEqual(
            titles["Concert des Ombres Punk"]["classification"],
            "POSSIBLE_CONCERT_OR_TOUR_REVIEW_ONLY")
        for row in clues:
            self.assertTrue(row["review_only"])
            self.assertFalse(row["festival_verified"])
            self.assertFalse(row["concert_verified"])
            self.assertFalse(row["date_verified"])
            self.assertFalse(row["publication_authorized"])
            self.assertTrue(row["detail_url_review_only"].startswith(SITE))
            self.assertNotIn("startDate", row)
            self.assertNotIn("officialSite", row)

        home = '<a href="/agenda">Agenda</a>'
        pages = {SITE: home, SITE+"agenda": index}
        result = scan(queue(), municipality(), TODAY,
                      fetch=lambda url: pages.get(url, "<h1>Page mairie</h1>"),
                      commune_lookup=geo, delegated_lookup=lambda _: None,
                      directory_fetch=dila)
        self.assertEqual(result["unknown_music_links_count"], 3)
        self.assertEqual(result["unknown_music_links_publications"], 0)
        self.assertFalse(result["publication_authorized"])
        self.assertEqual(result["publications"], 0)

    def test_unknown_music_links_are_not_repeated_current_known_festival(self):
        from national_municipal_pages_preflight import unknown_municipal_music_links
        html = """<a href="/evenement/known">Festival Foudre Libre 2027</a>
          <a href="/evenement/foudre-2027">Festival Foudre Libre</a>
          <a href="/evenement/other">Punk Rock Electrique inédit</a>
          <a href="/concerts">Concerts</a>
        """
        raw = unknown_municipal_music_links(html, SITE, SITE)
        self.assertEqual(len(raw), 3)  # Includes old name before dossier comparison.
        out = scan(queue(), municipality(), TODAY, fetch=lambda _: html,
                   commune_lookup=geo, delegated_lookup=lambda _: None,
                   directory_fetch=dila)
        clues = out["rows"][0]["unknown_music_links_review_only"]
        self.assertEqual(len(clues), 1)
        self.assertEqual(clues[0]["title_hint"], "Punk Rock Electrique inédit")
        self.assertFalse(out["publication_authorized"])

    def test_administrative_manifestations_never_become_music_leads(self):
        """Real live discovery regression: manifesto != indie music *Fest*."""
        from national_municipal_pages_preflight import unknown_municipal_music_links
        html = """<main><h1>Vie associative</h1>
          <a href="/demarches/demande-manifestation">
            Demande d'organisation de manifestation pour les associations
          </a>
          <a href="/associations/manifestations">
            Associations : manifestations et subventions
          </a>
          <a href="/evenement/festival-foudre">Festival Foudre 2027</a>
          <a href="/evenement/helixfest">HelixFest 2027</a>
          <a href="/evenement/germirockn-co">GermiRock'n Co #2</a>
          </main>"""
        clues = unknown_municipal_music_links(html, SITE, SITE)
        self.assertEqual(
            [x["title_hint"] for x in clues],
            ["Festival Foudre 2027", "HelixFest 2027",
             "GermiRock'n Co #2"])
        self.assertTrue(all("manifestation" not in x["title_hint"].lower()
                            for x in clues))
        self.assertTrue(all(x["publication_authorized"] is False
                            for x in clues))

    def test_unknown_music_refs_fail_closed_to_bad_links_overbudget_and_hidden(self):
        from national_municipal_pages_preflight import (
            unknown_municipal_music_links, MAX_UNKNOWN_MUSIC_LINKS)
        html = "<main>" + "".join(
            '<a href="/evenement/punk-' + str(i) +
            '">Punk Rock Festival ' + str(i) + '</a>' for i in range(40))
        html += ('<a href="/%2e%2e/admin">Punk Metal</a>'
                 '<a href="http://localhost/secret">Metal Festival</a>'
                 '<a href="/event?a=1">Rock Fest Unknown</a>'
                 '<a aria-hidden="true" href="/evil">Metal Hidden</a>'
                 '</main>')
        rows = unknown_municipal_music_links(html, SITE, SITE)
        self.assertEqual(len(rows), MAX_UNKNOWN_MUSIC_LINKS)
        self.assertEqual(len(set(x["detail_url_review_only"] for x in rows)),
                         MAX_UNKNOWN_MUSIC_LINKS)
        self.assertTrue(all("punk-" in x["detail_url_review_only"]
                            for x in rows))
        self.assertEqual(unknown_municipal_music_links(
            "<script>Festival Rock 2027</script>", SITE, SITE), [])
        self.assertEqual(unknown_municipal_music_links(
            "<main>Festival Rock 2027</main>", SITE, SITE), [])

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
