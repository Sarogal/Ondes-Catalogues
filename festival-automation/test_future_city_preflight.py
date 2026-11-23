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
    def test_signed_current_edition_date_and_department_locality_hero(self):
        # Realistic official event-site structure: year and municipality in
        # one paragraph; edition branding elsewhere in the same homepage.
        row = dict(ROW, slug="les-gueules-de-bois-2027",
                   name="Les Gueules de Bois 2027",
                   startDate="2027-08-19", endDate="2027-08-21",
                   officialSite="https://festivalgueulesdebois.com/",
                   department=None)
        site = row["officialSite"]
        html = (
            "<main><p>7e édition</p>"
            "<h2>Et cet été, on remet ça.</h2>"
            "<p>19, 20 &amp; 21 AOÛT 2027<br/>Légna (39) · Jura</p>"
            "<section><p>Les Gueules de Bois célèbrent le punk et le metal."
            "</p></section></main>")
        self.assertEqual(exact_edition_city(html, row), {
            "slug": row["slug"], "city": "Légna", "source": site})
        self.assertEqual(exact_city_from_official_site(
            row, fetcher=lambda _: html)["city"], "Légna")
        self.assertIsNone(exact_edition_city(
            html, dict(row, department="75")))
        self.assertIsNone(exact_edition_city(
            html, dict(row, city="Paris")))

    def test_dated_locality_hero_never_copies_historic_or_loose_town(self):
        row = dict(ROW, slug="les-gueules-de-bois-2027",
                   name="Les Gueules de Bois 2027",
                   startDate="2027-08-19", endDate="2027-08-21",
                   officialSite="https://festivalgueulesdebois.com/")
        current = "<p>19, 20 &amp; 21 août 2027<br/>Légna (39) · Jura</p>"
        identity = "<h1>Les Gueules de Bois</h1>"
        invalid = [
            identity + current.replace("2027", "2026"),
            identity + current.replace("Légna (39)", "Légna"),
            identity + current.replace("21 août", "22 août"),
            identity + current.replace("2027<br/>Légna", "2027</p><p>Légna"),
            identity + current.replace("<p>19,", "<script>19,")
            .replace("Jura</p>", "Jura</script>"),
            current,  # no festival identity anywhere on the same official page
        ]
        for html in invalid:
            with self.subTest(html=html[:100]):
                self.assertIsNone(exact_edition_city(html, row))
        two_towns = identity + current.replace(
            "Légna (39)", "Légna (39) ou Dole (39)")
        self.assertIsNone(exact_edition_city(two_towns, row))

    def test_confirmed_future_edition_without_dates_can_prove_a_city(self):
        from future_city_preflight import (
            undated_future_year, eligible_undated,
        )
        row = {
            "slug": "festival-exemple-2027",
            "name": "Festival Exemple 2027", "startDate": None, "endDate": None,
            "status": "Dates à venir", "officialSite": SITE,
            "showOnMap": False, "lat": None, "lon": None, "city": None,
        }
        html = (
            "<html><p>Festival Exemple : rendez-vous en 2027 "
            "à Colonne pour la prochaine édition.</p></html>"
        )
        self.assertEqual(undated_future_year(row, "2026-11-21"), 2027)
        self.assertEqual(eligible_undated(catalogue(row), "2026-11-21"), [row])
        self.assertEqual(exact_edition_city(html, row), {
            "slug": row["slug"], "city": "Colonne", "source": SITE,
        })
        calls = []
        self.assertEqual(exact_city_from_official_site(
            row, lambda url: calls.append(url) or html), {
            "slug": row["slug"], "city": "Colonne", "source": SITE,
        })
        self.assertEqual(calls, [SITE])

    def test_official_future_edition_hero_owns_town_and_department(self):
        row = {
            "slug": "esqui-riot-2027", "name": "Esqui'Riot 2027",
            "startDate": None, "endDate": None, "status": "Dates à venir",
            "officialSite": "https://esquiriot.fr/", "showOnMap": False,
            "lat": None, "lon": None, "city": None,
        }
        future = ("<section><p>Édition 2 — Été 2027</p>"
                  "<p>Festival Punk · Métal · Rock</p>"
                  "<p>Sainte-Hélène</p><p>Gironde</p>"
                  "<p>499</p><p>Places</p></section>")
        past = ("<section><p>Édition 2026</p><h2>Retour en images</h2>"
                "<p>La première édition en quelques clichés.</p></section>")
        html = "<h1>Esqui'Riot</h1>" + future + past
        claim = {"slug": row["slug"], "city": "Sainte-Hélène",
                 "source": row["officialSite"], "departmentLabel": "Gironde"}
        self.assertEqual(exact_edition_city(html, row), claim)
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: html), claim)
        invalid = [
            future + past,
            "<h1>Esqui'Riot</h1>" +
                future.replace("2027", "2026") + past,
            "<h1>Esqui'Riot</h1>" + future.replace(
                "<p>Gironde</p>", "</section><section><p>Gironde</p>") + past,
            "<h1>Esqui'Riot</h1>" +
                future.replace("<p>Sainte-Hélène</p>",
                               "<p hidden>Sainte-Hélène</p>") + past,
            "<h1>Esqui'Riot</h1>" +
                future.replace("<p>Édition 2 — Été 2027</p>",
                               "<p>Édition 2 — Été 2027 annulée</p>") + past,
            "<h1>Esqui'Riot</h1>" + future +
                future.replace("Sainte-Hélène", "Bordeaux") + past,
        ]
        for sample in invalid:
            with self.subTest(sample=sample[:120]):
                self.assertIsNone(exact_edition_city(sample, row))

    def test_logo_only_festival_name_can_be_verified_in_official_html_title(self):
        # The real Esqui'Riot site renders its brand as a logo. Its SEO title
        # still contains an OLD 2026 date, which must never become 2027 proof.
        row = {
            "slug": "esqui-riot-2027", "name": "Esqui'Riot 2027",
            "startDate": None, "endDate": None, "status": "Dates à venir",
            "officialSite": "https://esquiriot.fr/", "showOnMap": False,
            "lat": None, "lon": None, "city": None,
        }
        head = ("<head><title>Esqui'Riot — 11 Juillet 2026 — "
                "18€ en prévente</title></head>")
        banner = ("<section><p>Édition 2 — Été 2027</p>"
                  "<p>Festival Punk · Métal · Rock</p>"
                  "<p>Sainte-Hélène</p><p>Gironde</p>"
                  "<p>499</p><p>Places</p></section>")
        history = ("<section><h2>Édition 2026</h2>"
                   "<p>Retour en images de la première édition.</p></section>")
        html = ("<html>" + head + "<body><header>"
                "<img src='/images/logo-blanc.png' alt='Logo du festival'/>"
                "</header><main>" + banner + history + "</main></body></html>")
        expected = {"slug": row["slug"], "city": "Sainte-Hélène",
                    "source": row["officialSite"],
                    "departmentLabel": "Gironde"}
        self.assertEqual(exact_edition_city(html, row), expected)
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: html), expected)
        bad = [
            html.replace("Esqui'Riot —", "Un autre festival —"),
            html.replace("Édition 2 — Été 2027", "Édition 2 — Été 2026"),
            html.replace("<p>Gironde</p>", "</section><section><p>Gironde</p>"),
            html.replace("<p>Sainte-Hélène</p>", "<p hidden>Sainte-Hélène</p>"),
            html.replace("Sainte-Hélène", "Sainte-Hélène et Bordeaux"),
            "<html>" + head + "<body><p>Édition 2027</p>"
            "<p>Ancien lieu : Sainte-Hélène en Gironde</p></body></html>",
        ]
        for snippet in bad:
            with self.subTest(html=snippet[:110]):
                self.assertIsNone(exact_edition_city(snippet, row))

    def test_dated_city_hero_can_use_festival_identity_in_html_title(self):
        row = {**ROW, "slug": "les-gueules-de-bois-2027",
               "name": "Les Gueules de Bois 2027",
               "startDate": "2027-08-19", "endDate": "2027-08-21"}
        title = ("<head><title>Festival Les Gueules de Bois — "
                 "billetterie officielle</title></head>")
        body = ("<main><section><p>7ᵉ édition</p>"
                "<p>19, 20 &amp; 21 AOÛT 2027<br/>Légna (39) · Jura</p>"
                "</section></main>")
        got = exact_edition_city(title + body, row)
        self.assertEqual(got["city"], "Légna")
        self.assertIsNone(exact_edition_city(
            title.replace("Les Gueules de Bois", "Un Autre Festival") + body,
            row))
        self.assertIsNone(exact_edition_city(
            title + body.replace("2027", "2026"), row))

    def test_undated_future_local_hero_isolated_from_sibling_archive_recap(self):
        row = {
            "slug": "esqui-riot-2027", "name": "Esqui'Riot 2027",
            "startDate": None, "endDate": None, "status": "Dates à venir",
            "officialSite": "https://esquiriot.fr/", "showOnMap": False,
            "lat": None, "lon": None, "city": None,
        }
        identity = ("<head><title>Esqui'Riot — édition 2026"
                    "</title></head>")
        current = ("<p>Édition 2 — Été 2027</p>"
                   "<p>Festival Punk · Métal · Rock</p>"
                   "<p>Sainte-Hélène</p><p>Gironde</p>")
        archive = ("<h2>Édition 2026 — Retour en images</h2>"
                   "<p>La programmation 2026 a réuni plusieurs groupes.</p>")
        html = identity + "<section>" + current + archive + "</section>"
        expected = {"slug": row["slug"], "city": "Sainte-Hélène",
                    "source": row["officialSite"],
                    "departmentLabel": "Gironde"}
        self.assertEqual(exact_edition_city(html, row), expected)
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: html), expected)
        for invalid in (
            identity + "<section>" + current.replace(
                "Été 2027", "Été 2026") + archive + "</section>",
            identity + "<section>" + current.replace(
                "Festival Punk", "Festival Punk 2026") + archive + "</section>",
            identity + "<section>" + current.replace(
                "Sainte-Hélène", "Sainte-Hélène 2026") + archive + "</section>",
            identity + "<section>" + current.replace(
                "Gironde", "Gironde 2026") + archive + "</section>",
            identity + "<section><p>Édition 2 — Été 2027</p>"
                + archive + "<p>Festival Punk · Métal · Rock</p>"
                "<p>Sainte-Hélène</p><p>Gironde</p></section>",
        ):
            with self.subTest(sample=invalid[:130]):
                self.assertIsNone(exact_edition_city(invalid, row))

    def test_undated_city_must_be_on_explicit_future_edition_paragraph(self):
        row = {
            "slug": "festival-exemple-2027",
            "name": "Festival Exemple 2027", "startDate": None, "endDate": None,
            "status": "Dates à venir", "officialSite": SITE,
            "showOnMap": False, "lat": None, "lon": None, "city": None,
        }
        invalid = [
            "<p>Festival Exemple 2026 à Colonne</p>"
            "<p>Festival Exemple : édition 2027</p>",
            "<p>Festival Exemple : rendez-vous en 2027 à Colonne"
            " et à Bordeaux.</p>",
            "<p>Festival Exemple : préparation de l'édition 2027"
            " à Colonne sous réserve de financement.</p>",
            "<p>Festival Exemple : édition 2027 à Colonne annulée.</p>",
            "<p style='display:none'>Festival Exemple : édition 2027 "
            "à Colonne.</p>",
            "<p>Festival Exemple : édition 2027 à Colonne 12-13 juin 2027.</p>",
        ]
        for html in invalid:
            with self.subTest(html=html):
                self.assertIsNone(exact_edition_city(html, row))
        self.assertIsNone(exact_edition_city(
            "<p>Festival Exemple : édition 2027 à Bordeaux.</p>",
            {**row, "city": "Colonne"}))
        self.assertEqual(exact_edition_city(
            "<p>Festival Exemple : édition 2027 à Colonne.</p>",
            {**row, "city": "Colonne"})["city"], "Colonne")
        for forged in (
            {"startDate": "2027-01-01"},
            {"endDate": "2027-01-01"},
            {"status": "Confirmé"},
            {"showOnMap": True},
            {"slug": "festival-exemple-2026"},
            {"lat": 48.0},
        ):
            with self.subTest(forged=forged):
                from future_city_preflight import undated_future_year
                self.assertIsNone(undated_future_year(
                    {**row, **forged}, "2026-11-21"))

    def test_undated_geo_cannot_skip_two_independent_days(self):
        row = {
            "slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
            "startDate": None, "endDate": None, "status": "Dates à venir",
            "officialSite": SITE, "showOnMap": False,
            "lat": None, "lon": None, "city": None,
        }
        html = ("<p>Festival Exemple revient en 2027 à Colonne.</p>")
        state = {"schema": "grossesondes.source-watch.v1"}
        first = review(state, catalogue(row), "2026-11-20",
                       lambda _: html)
        self.assertEqual(first["checked"], 1)
        self.assertEqual(first["first_day"], 1)
        same = review(state, catalogue(row), "2026-11-20",
                      lambda _: html)
        self.assertEqual(same["two_day_stable"], 0)
        next_day = review(state, catalogue(row), "2026-11-21",
                          lambda _: html)
        # The exact state logic never counts repeated checks on the same day
        # as separate proofs; only two civil dates can stabilize it.
        self.assertLessEqual(next_day["two_day_stable"], 1)
        self.assertTrue(next_day["publication_authorized"] is False)

    def test_festival_title_location_and_named_future_dates_stay_tied(self):
        # Real first-party design: the homepage SEO title has the declared
        # festival town and département, while the exact 2027 edition dates
        # are announced in a separately branded visible paragraph.
        row = {**ROW, "slug": "colomb-in-rock-festival-2027",
               "name": "Colomb'in Rock Festival 2027",
               "startDate": "2027-08-13", "endDate": "2027-08-14",
               "officialSite": "https://www.colombin-rock.fr/"}
        title = (
            "<head><title>Un des plus grands festivals tributes de France "
            "mettant en scène des Tribute Bands nationaux et internationaux "
            "à Colombe-lès-Vesoul (70-Haute-Saône).</title></head>")
        body = (
            "<main><p>Le Colomb’in Rock Festival est organisé "
            "tous les 13 Août et 14 Août.</p>"
            "<p>La prochaine édition anniversaire du "
            "Colomb’in Rock Festival aura lieu les 13 et 14 Août 2027.</p>"
            "<p>Retrouvez la programmation 2027</p></main>")
        expected = {"slug": row["slug"], "city": "Colombe-lès-Vesoul",
                    "source": row["officialSite"]}
        self.assertEqual(exact_edition_city(title + body, row), expected)
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: title + body), expected)
        invalid = (
            title + body.replace("13 et 14 Août 2027", "14 et 15 Août 2027"),
            title + body.replace("13 et 14 Août 2027", "13 et 14 Août 2026"),
            title.replace("à Colombe-lès-Vesoul", "près de Colombe-lès-Vesoul")
                + body,
            title.replace("(70-Haute-Saône)", "(75)") +
                body.replace("13 et 14 Août 2027", "13 et 14 Août 2026"),
            title.replace("festivals tributes", "salles de spectacles") + body,
            title + body.replace("Colomb’in Rock Festival aura lieu",
                                 "Un autre festival aura lieu"),
            title.replace("</title>", " et à Paris (75)</title>") + body,
            title + body.replace("13 et 14 Août 2027",
                                 "13 et 14 Août 2027 annulée"),
        )
        for html in invalid:
            with self.subTest(variant=html[:135]):
                self.assertIsNone(exact_edition_city(html, row))
        self.assertIsNone(exact_edition_city(
            title + body, {**row, "department": "75"}))
        self.assertIsNone(exact_edition_city(
            title + body, {**row, "city": "Paris"}))

    def test_official_current_dates_and_venue_directions_prove_town(self):
        row = dict(ROW, slug="helixfest-2027", name="HelixFest 2027",
                   startDate="2027-04-23", endDate="2027-04-24",
                   officialSite="https://helixfest.fr/")
        identity = "<h1>HELIXFEST</h1>"
        current = (
            "<section><h2>INFORMATIONS</h2><p>On vous donne rendez-vous "
            "les 23 &amp; 24 avril 2027, dans la salle<br/>"
            " le 750 à La Bâtie-Neuve</p></section>")
        old = "<section><p>HelixFest 2026, c'était ça !</p></section>"
        got = exact_edition_city(identity + old + current, row)
        self.assertEqual(got, {
            "slug": row["slug"], "city": "La Bâtie-Neuve",
            "source": row["officialSite"],
        })
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: identity + old + current), got)
        invalid = [
            current,  # no festival identity on the first-party page
            identity + current.replace("24 avril", "25 avril"),
            identity + current.replace("2027", "2026"),
            identity + current.replace("dans la salle", "pour le concert"),
            identity + current.replace("à La Bâtie-Neuve", "à La Bâtie-Neuve et à Gap"),
            identity + current.replace("salle<br/> le 750 à", "salle</p><p>le 750 à"),
            identity + current.replace("<p>On vous", "<p hidden>On vous"),
        ]
        for html in invalid:
            with self.subTest(html=html[:100]):
                self.assertIsNone(exact_edition_city(html, row))

    def test_official_current_homepage_dates_and_present_tense_town(self):
        """A current festival homepage can separate its dates from its town."""
        row = dict(ROW, slug="le-gros-tonneau-2027",
                   name="Le Gros Tonneau 2027",
                   startDate="2027-05-07", endDate="2027-05-08",
                   officialSite="https://legrostonneau-festival.fr/")
        hero = ("<main><h1>Le Gros Tonneau Festival</h1>"
                "<p>.07.08 Mai 2027</p>"
                "<h2>Replonge dans le millésime 2026 du GROS TONNEAU</h2>"
                "<h2>Le Gros Tonneau, festival Punk, Hardcore &amp; Métal</h2>")
        venue = (
            "<p>Le Gros Tonneau est un festival indépendant consacré "
            "aux musiques Punk, Hardcore et Metal qui se déroule "
            "à Artonne, proche de Clermont-Ferrand, en Auvergne.</p></main>")
        expected = {"slug": row["slug"], "city": "Artonne",
                    "source": row["officialSite"]}
        self.assertEqual(exact_edition_city(hero + venue, row), expected)
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: hero + venue), expected)
        for invalid in (
            hero.replace("2027", "2026", 1) + venue,
            hero.replace("07.08", "07.09") + venue,
            hero.replace("Le Gros Tonneau Festival",
                         "Le festival sans rapport") + venue,
            hero.replace("07.08 Mai 2027", "Billetterie 2027") + venue,
            hero + venue.replace("se déroule", "se déroulait"),
            hero + venue.replace("à Artonne", "à Artonne et à Limoges"),
            hero + venue.replace("qui se déroule", "qui en 2026 se déroule"),
            hero + venue.replace("<p>Le Gros Tonneau",
                                 "<p hidden>Le Gros Tonneau"),
            hero + venue.replace("</main>", "") +
                "<p>Le Gros Tonneau se déroule à Bordeaux.</p></main>",
        ):
            with self.subTest(variant=invalid[:120]):
                self.assertIsNone(exact_edition_city(invalid, row))

    def test_city_rotation_covers_thirteen_dossiers_in_two_daily_runs(self):
        from future_city_preflight import MAX_CHECKS
        self.assertEqual(MAX_CHECKS, 8)
        rows = [
            {**ROW, "slug": "festival-exemple-" + str(i) + "-2027",
             "name": "Festival Exemple " + str(i) + " 2027",
             "officialSite": "https://festival-exemple" + str(i) + ".fr/"}
            for i in range(13)
        ]
        # Use a valid signed city row shape but no proof on an empty site.
        report_catalogue = {"schema": 1, "festivals": rows}
        state = {"schema": "grossesondes.source-watch.v1"}
        first = review(state, report_catalogue, "2026-11-23",
                       lambda _: "<p>Informations à venir</p>", limit=8)
        second = review(state, report_catalogue, "2026-11-23",
                        lambda _: "<p>Informations à venir</p>", limit=8)
        self.assertEqual(first["checked"], 8)
        self.assertEqual(second["checked"], 8)
        self.assertEqual(len({x["slug"] for x in first["findings"] +
                              second["findings"]}), 13)
        with self.assertRaises(ValueError):
            review(state, report_catalogue, "2026-11-23",
                   lambda _: "", limit=9)

    def test_department_change_resets_two_day_city_proof(self):
        row = {
            "slug": "esqui-riot-2027", "name": "Esqui'Riot 2027",
            "startDate": None, "endDate": None, "status": "Dates à venir",
            "officialSite": "https://esquiriot.fr/", "showOnMap": False,
            "lat": None, "lon": None, "city": None,
        }
        def official(department):
            return ("<h1>Esqui'Riot</h1><section>"
                    "<p>Édition 2 — Été 2027</p>"
                    "<p>Festival Punk · Métal · Rock</p>"
                    "<p>Sainte-Hélène</p><p>" + department + "</p></section>")
        state = {"schema": "grossesondes.source-watch.v1"}
        first = review(state, catalogue(row), "2026-11-23",
                       lambda _: official("Gironde"))
        changed = review(state, catalogue(row), "2026-11-24",
                         lambda _: official("Morbihan"))
        self.assertEqual(first["first_day"], 1)
        self.assertEqual(changed["first_day"], 1)
        self.assertEqual(changed["two_day_stable"], 0)
        self.assertEqual(changed["findings"][0]["first_seen"], "2026-11-24")
        confirmed = review(state, catalogue(row), "2026-11-25",
                           lambda _: official("Morbihan"))
        self.assertEqual(confirmed["two_day_stable"], 1)
        self.assertEqual(confirmed["findings"][0]
                         ["candidate_city"]["departmentLabel"], "Morbihan")

    def test_current_festival_city_in_separate_official_edition_hero(self):
        """Real-world first-party layout: title in brand, city after dates."""
        row = {
            **ROW, "slug": "la-sainte-rock-festival-2027",
            "name": "La Sainte Rock Festival 2027",
            "startDate": "2027-04-23", "endDate": "2027-04-24",
            "officialSite": "https://lasainterockfestival.fr/",
        }
        hero = (
            "<section><p>Wild & Civilized et le 6MIC présentent</p>"
            "<div>4e édition · 23 &amp; 24 avril 2027 · Aix-en-Provence</div>"
            "<h1>Ça va faire du bruit</h1></section>"
            "<blockquote>Pour l'amour du Rock, je rêvais de créer "
            "La Sainte Rock Festival.</blockquote>"
        )
        result = exact_edition_city(hero, row)
        self.assertEqual(result, {
            "slug": row["slug"], "city": "Aix-en-Provence",
            "source": row["officialSite"],
        })
        self.assertEqual(exact_city_from_official_site(
            row, lambda _: hero), result)
        # Only the visible official current-edition caption is sufficient.
        # A footer-only city, another year, an unnamed event, or two towns
        # cannot enrich the signed festival identity.
        invalid = [
            hero.replace("2027 · Aix", "2026 · Aix"),
            hero.replace("2027 · Aix", "2027</div><p>à Aix"),
            hero.replace("La Sainte Rock Festival", "autre festival"),
            hero.replace("4e édition", "Le concert"),
            hero.replace("Aix-en-Provence", "Aix-en-Provence · Bordeaux"),
            hero.replace("2027 · Aix", "2027 · Bordeaux")
                .replace("La Sainte Rock Festival",
                         "Festival sans rapport"),
        ]
        for sample in invalid:
            with self.subTest(sample=sample):
                self.assertIsNone(exact_edition_city(sample, row))
        # Historical footers are no longer allowed to become a 2027 pin.
        other = (
            "<p>La Sainte Rock Festival 2027 : dates à venir</p>"
            "<p>La Sainte Rock Festival 2026 à Aix-en-Provence</p>"
        )
        self.assertIsNone(exact_edition_city(other, row))

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
                '<a href="/inscription-benevoles-2027">Bénévoles 2027</a>'
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
                   catalogue(), "2026-11-20", lambda _: MESSAGE, limit=9)
