import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from future_city_preflight import (
    SCHEMA, STATE_KEY, exact_edition_city, exact_city_from_official_site,
    official_city_links, review,
)

SITE = "https://festival-exemple.fr/"
ROW = {
    "slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
    "startDate": "2027-07-02", "endDate": "2027-07-03",
    "officialSite": SITE, "city": None,
    "lat": None, "lon": None, "showOnMap": False,
}
MESSAGE = ("<html><p>Le Festival Exemple 2027 revient les "
           "2 et 3 juillet 2027 à Colonne pour sa quatrième édition !</p></html>")
OLD_MESSAGE = ("<html><p>Le Festival Exemple 2026 revient les "
               "3 et 4 juillet 2026 à Colonne.</p></html>")


def ld(city="Colonne", country="FR", **changes):
    event = {
        "@context": "https://schema.org", "@type": "MusicFestival",
        "name": "Festival Exemple 2027", "startDate": "2027-07-02",
        "endDate": "2027-07-03",
        "location": {"@type": "Place", "address": {
            "addressLocality": city, "addressCountry": country}},
    }
    event.update(changes)
    return "<script type='application/ld+json'>" + json.dumps(event) + "</script>"


def catalogue(row=ROW):
    return {"schema": 1, "festivals": [row]}


class FutureCityProofTests(unittest.TestCase):
    def test_current_year_city_visible_in_one_dated_official_paragraph(self):
        value = exact_edition_city(MESSAGE, ROW)
        self.assertEqual(value, {
            "slug": ROW["slug"], "city": "Colonne", "source": SITE,
        })
        self.assertIsNone(exact_edition_city(OLD_MESSAGE, ROW))
        self.assertIsNone(exact_edition_city(
            "<p>Festival Exemple 2027 à Colonne.</p>"
            "<p>2 et 3 juillet 2027.</p>", ROW))
        self.assertIsNone(exact_edition_city(
            MESSAGE.replace("2 et 3 juillet 2027", "3 et 4 juillet 2027"), ROW))
        self.assertIsNone(exact_edition_city(
            MESSAGE.replace("revient", "est annulé et revient"), ROW))
        self.assertIsNone(exact_edition_city(
            "<p style='display:none'>Le Festival Exemple 2027 revient les "
            "2 et 3 juillet 2027 à Colonne.</p>", ROW))

    def test_city_requires_one_current_festival_and_no_conflicts(self):
        self.assertIsNone(exact_edition_city(
            MESSAGE.replace("à Colonne", "à Colonne et à Bordeaux"), ROW))
        self.assertIsNone(exact_edition_city(
            MESSAGE.replace("à Colonne", "à Bordeaux"), {**ROW, "city": "Colonne"}))
        self.assertIsNone(exact_edition_city(
            MESSAGE.replace("2027", "2026", 1), ROW))
        self.assertIsNone(exact_edition_city(
            "<p>Le Festival Exemple 2027 revient les 2 et 3 juillet 2027 "
            "à Colonne puis à Bordeaux.</p>", ROW))

    def test_exact_jsonld_city_without_coordinates_works(self):
        self.assertEqual(exact_edition_city("<html>" + ld() + "</html>", ROW)["city"],
                         "Colonne")
        self.assertIsNone(exact_edition_city(ld(country="US"), ROW))
        self.assertIsNone(exact_edition_city(ld(city="London", country="GB")
                                             + MESSAGE, ROW))
        self.assertIsNone(exact_edition_city(ld(
            eventStatus="https://schema.org/EventCancelled") + MESSAGE, ROW))
        self.assertIsNone(exact_edition_city(ld(startDate="2027-07-05")
                                             + MESSAGE, ROW))
        self.assertIsNone(exact_edition_city(
            ld(city="Colonne")+ld(city="Bordeaux"), ROW))

    def test_link_selection_bounded_to_same_host_current_edition(self):
        home = """<html>
          <a href="/nouvelle-edition-2027">Nouvelle édition en 2027</a>
          <a href="/2026/acces">Accès de 2026</a>
          <a href="http://festival-exemple.fr/edition-2027">No TLS</a>
          <a href="https://evil.example/edition-2027">External</a>
          <a href="//127.0.0.1/2027">SSRF</a>
          <a href="/%2e%2e/admin/edition-2027">Traversal</a>
          <a href="/edition-2027?token=xyz">Query URL</a>
          <a href="/actu/">Actualités</a>
          <a href="/infos-pratiques">Infos pratiques</a>
          <a href="/contact">Contact</a>
        </html>"""
        found = official_city_links(home, SITE)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0], SITE + "nouvelle-edition-2027")
        self.assertNotIn("127.0.0.1", str(found))
        self.assertNotIn("evil.example", str(found))

    def test_year_specific_news_page_from_signed_site_is_revalidated(self):
        home = "<a href='/nouvelle-edition-2027'>Nouvelle édition 2027</a>"
        news = SITE + "nouvelle-edition-2027"
        calls = []
        def fetch(url):
            calls.append(url)
            return home if url == SITE else MESSAGE
        claim = exact_city_from_official_site(ROW, fetch)
        self.assertEqual(calls, [SITE, news])
        self.assertEqual(claim["city"], "Colonne")
        self.assertEqual(claim["source"], SITE)
        self.assertIsNone(exact_city_from_official_site(
            ROW, lambda url: home if url == SITE else OLD_MESSAGE))

    def test_conflicting_official_current_edition_towns_fail_closed(self):
        home = (MESSAGE + "<a href='/nouvelle-edition-2027'>"
                "Nouvelle édition 2027</a>")
        wrong = MESSAGE.replace("Colonne", "Bordeaux")
        self.assertIsNone(exact_city_from_official_site(
            ROW, lambda url: home if url == SITE else wrong))

    def test_news_index_is_not_starved_by_multiple_current_year_menu_links(self):
        home = ('<main>'
                '<a href="/programme-2027">Programme 2027</a>'
                '<a href="/partenaires-2027">Partenaires 2027</a>'
                '<a href="/benevoles-2027">Bénévoles 2027</a>'
                '<a href="/actualites">Actualités</a>'
                '<a href="https://evil.example/news">Actualités externes</a>'
                '</main>')
        index = ('<a href="/news/festival-edition-2027">'
                 'La nouvelle édition 2027</a>'
                 '<a href="/2026/retrospective">Ancienne édition 2026</a>')
        pages = {
            SITE: home,
            SITE + "actualites": index,
            SITE + "programme-2027": "<main>Programmation à venir</main>",
            SITE + "news/festival-edition-2027": MESSAGE,
        }
        first = official_city_links(home, SITE)
        self.assertEqual(len(first), 2)
        self.assertIn(SITE + "actualites", first)
        self.assertNotIn("evil.example", str(first))
        calls = []
        def fetch(url):
            calls.append(url)
            return pages[url]
        proof = exact_city_from_official_site(ROW, fetch)
        self.assertIsNotNone(proof)
        self.assertEqual(proof["city"], "Colonne")
        self.assertEqual(calls, [
            SITE, SITE + "programme-2027", SITE + "actualites",
            SITE + "news/festival-edition-2027"])
        self.assertEqual(len(calls), 4)

    def test_official_current_year_article_discovered_through_news_index(self):
        home = ('<a href="/2027">Programme 2027</a>'
                '<a href="/actualites">Actualités</a>')
        listing = ('<a href="/nouvelle-edition-2027">'
                   'Nouvelle édition 2027</a>'
                   '<a href="https://evil.example/edition-2027">'
                   'Nouvelle édition 2027 externe</a>'
                   '<a href="/2026/edition">Édition 2026</a>')
        pages = {
            SITE: home,
            SITE + "2027": "<h1>Programmation 2027</h1>",
            SITE + "actualites": listing,
            SITE + "nouvelle-edition-2027": MESSAGE,
        }
        visits = []
        def fetch(url):
            visits.append(url)
            return pages[url]
        clue = exact_city_from_official_site(ROW, fetch)
        self.assertEqual(clue["city"], "Colonne")
        self.assertEqual(visits, [
            SITE, SITE + "2027", SITE + "actualites",
            SITE + "nouvelle-edition-2027",
        ])
        self.assertNotIn("evil.example", str(visits))

    def test_nested_articles_must_be_edition_specific_and_bounded(self):
        homepage = ('<a href="/actualites">Actualités</a>'
                    '<a href="/news">News</a>')
        listing = ('<a href="/news/saison-2026">Édition 2026</a>'
                   '<a href="/news/edition-2027">Édition 2027</a>'
                   '<a href="/news/reprise-2027">Reprise 2027</a>'
                   '<a href="/news/autre-2027">Autre 2027</a>'
                   '<a href="/%2e%2e/news/2027">Chemin trompeur 2027</a>'
                   '<a href="http://127.0.0.1/news/2027">IP locale 2027</a>'
                   '<a href="/news/2027?url=internal">Query 2027</a>')
        visits = []
        def fetch(url):
            visits.append(url)
            if url == SITE:
                return homepage
            if url in (SITE + "news", SITE + "actualites"):
                return listing
            return "<h1>Ancienne annonce 2026</h1>"
        result = exact_city_from_official_site(ROW, fetch)
        self.assertIsNone(result)
        self.assertLessEqual(len(visits), 5)
        self.assertEqual(len(visits), len(set(visits)))
        self.assertNotIn("127.0.0.1", str(visits))
        self.assertNotIn("saison-2026", str(visits))
        self.assertNotIn("url=internal", str(visits))

    def test_nested_official_article_from_2026_cannot_prove_2027(self):
        home = '<a href="/actualites">Actualités</a>'
        listing = ('<a href="/reprise-2026">Festival 2026</a>'
                   '<a href="/reprise-2027">Festival 2027</a>')
        source = {
            SITE: home,
            SITE + "actualites": listing,
            SITE + "reprise-2027": OLD_MESSAGE,
        }
        self.assertIsNone(exact_city_from_official_site(
            ROW, lambda url: source[url]))

    def test_conflict_between_homepage_and_nested_news_vetoes_town(self):
        home = MESSAGE + '<a href="/actualites">Actualités</a>'
        index = '<a href="/nouvelle-edition-2027">Nouvelle édition 2027</a>'
        source = {
            SITE: home, SITE + "actualites": index,
            SITE + "nouvelle-edition-2027": MESSAGE.replace("Colonne", "Bordeaux"),
        }
        self.assertIsNone(exact_city_from_official_site(
            ROW, lambda url: source[url]))

    def test_day_one_and_day_two_are_separate_calendar_dates(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        one = review(state, catalogue(), "2026-11-20",
                     lambda _: MESSAGE)
        self.assertEqual(one["first_day"], 1)
        self.assertEqual(one["two_day_stable"], 0)
        again = review(state, catalogue(), "2026-11-20",
                       lambda _: MESSAGE)
        self.assertEqual(again["two_day_stable"], 0)
        next_day = review(state, catalogue(), "2026-11-21",
                          lambda _: MESSAGE)
        self.assertEqual(next_day["two_day_stable"], 1)
        self.assertFalse(next_day["publication_authorized"])
        self.assertFalse(next_day["publisher_city_sync_connected"])
        self.assertEqual(next_day["schema"], SCHEMA)
        self.assertEqual(state[STATE_KEY][ROW["slug"]]["firstSeen"],
                         "2026-11-20")
        third = review(state, catalogue(), "2026-11-21", lambda _: MESSAGE)
        self.assertEqual(third["two_day_stable"], 1)

    def test_changed_or_missed_day_renews_first_observation(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        review(state, catalogue(), "2026-11-20", lambda _: MESSAGE)
        changed = MESSAGE.replace("Colonne", "Bordeaux")
        result = review(state, catalogue(), "2026-11-21", lambda _: changed)
        self.assertEqual(result["first_day"], 1)
        late = review(state, catalogue(), "2026-11-23", lambda _: changed)
        self.assertEqual(late["first_day"], 1)

    def test_untrusted_signed_home_and_private_url_never_fetched(self):
        row = {**ROW, "officialSite": "http://127.0.0.1/private"}
        state = {"schema": "grossesondes.source-watch.v1",
                 STATE_KEY: {ROW["slug"]: {"firstSeen": "2026-11-19",
                          "url": "http://localhost/private", "digest": "forged"}}}
        reads = []
        result = review(state, catalogue(row), "2026-11-20",
                        lambda url: reads.append(url))
        self.assertEqual(result["checked"], 0)
        self.assertEqual(reads, [])
        self.assertEqual(state[STATE_KEY], {})

    def test_non_geo_edition_and_corrupt_state_are_rejected(self):
        with self.assertRaises(ValueError):
            review({}, catalogue(), "2026-11-20", lambda _: MESSAGE)
        with self.assertRaises(ValueError):
            review({"schema": "grossesondes.source-watch.v1"},
                   catalogue(), "2026-11-20", lambda _: MESSAGE, limit=5)
