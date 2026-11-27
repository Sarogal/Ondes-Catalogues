"""Offline, exact-source regression for recurring festival updates."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from grossesondes_existing_official_updates import (
    apply_independently_verified_updates, linked_pages, page,
    signed_rotation, listed_artists, advertised_passes,
    current_official_ticket_city,
)
from grossesondes_cloud_sync import _verified_official_update_delta

DAY = "2026-11-22"
MOZHELL = "https://www.mozhell.fr/fr/"
ARTICLE = "https://www.mozhell.fr/fr/3-groupes-annonces-et-billetterie-ouverte"
MOTO = "https://www.motocultor-festival.com/"
MOTO_NEWS = MOTO + "actualites/21-nouveaux-groupes/"

def festival(slug, site, *, lineup=None, dates=("2027-07-23", "2027-07-25"), price=None):
    names = [] if lineup is None else lineup
    return {"slug": slug, "name": slug + " 2027",
            "startDate": dates[0], "endDate": dates[1],
            "officialSite": site, "lineup": names,
            "bands": len(names), "price": price,
            "notes": "Édition future", "lastVerified": "2026-11-18",
            "auditSources": [site],
            "showOnMap": False, "lat": None, "lon": None}

def doc(*rows):
    return {"schema": 1, "generatedAt": "2026-11-18",
            "festivals": [deepcopy(r) for r in rows]}

HOME = (
    "<main><h1>MozHell Open Air 2027</h1>"
    "<p>Festival métal en 2027 les 23, 24, 25 juillet.</p>"
    '<a href="/fr/3-groupes-annonces-et-billetterie-ouverte">'
    "3 groupes annoncés et billetterie ouverte</a>"
    '<a href="https://outside.example/programmation">Fake</a>'
    "</main>")
NEWS = (
    "<article><p>Ultra Vomit débarque au MozHell en 2027 ! "
    "Aux côtés de THE ARRS et LocoMuerte.</p>"
    "<h2>Trois groupes, trois énergies</h2><ul>"
    "<li><strong>Ultra Vomit</strong> c'est le metal parodique.</li>"
    "<li><strong>THE ARRS</strong> fait son retour.</li>"
    "<li><strong>LocoMuerte</strong> débarque pour le crossover.</li>"
    "</ul><h2>Early pass 3 jours</h2>"
    "<p>Les PASS 3 jours sont en vente au tarif early de "
    "129,90€ (hors frais). Disponibles en quantité limitée.</p>"
    "</article>")
MOTO_HOME = (
    "<main><h1>Motocultor Festival 2027 — 19 au 22 août 2027</h1>"
    "<p>Programmation 2027 : groupes annoncés.</p>"
    '<a href="/actualites/21-nouveaux-groupes/">'
    "21 nouveaux noms rejoignent l'affiche</a></main>")
MOTO_ARTICLE = (
    "<main><article><h1>21 nouveaux noms rejoignent l'affiche !</h1>"
    "<p>La 18e édition continue avec 21 nouveaux groupes "
    "attendus du 19 au 22 août à Carhaix :</p>"
    "<p>Alestorm, Cavalera Chaos A.D., DevilDriver, Eluveitie, "
    "Gogol Bordello, Katatonia, Sventevith, Agriculture, "
    "Flotsam &amp; Jetsam, Grima, Villagers of Ioannina City, "
    "Dirty Sound Magnet, Godsleep, Gorod, Holy Fawn, "
    "Les Bâtards du Roi, Les Garçons Bouchers, Lion’s Law, "
    "Spitting Glass, Suicidal Angels et VCTMS.</p>"
    "</article></main>")


class ExistingOfficialFestivalTests(unittest.TestCase):
    def test_current_official_poster_discovery_is_review_only(self):
        from grossesondes_existing_official_updates import current_official_poster_candidates
        site = "https://festival-exemple.fr/"
        row = festival("festival-123", site)
        row["name"] = "Festival 123 2027"
        html = ('<main><img src="/images/123-2027.jpg">'
                '<img src="/images/123-2026.jpg">'
                '<img src="/images/123-2026-2027.jpg">'
                '<img src="https://external.example/123-2027.jpg">'
                '<img hidden src="/images/affiche-2027.png">'
                '<div hidden><img src="/images/poster-2027.jpg"></div>'
                '<img src="/images/other-2027.png">'
                '<img src="/images/123-2027.svg">'
                '<img src="/images/123-2027.jpg?x=1">'
                '<footer><img src="/images/123-2027-footer.jpg"></footer></main>')
        self.assertEqual(current_official_poster_candidates(html, site, row),
                         [site + "images/123-2027.jpg"])
        self.assertEqual(row["lineup"], [])
        self.assertIsNone(row["lat"])

    def test_poster_hero_and_lazy_images_but_not_logo_or_hidden_navigation(self):
        from grossesondes_existing_official_updates import current_official_poster_candidates
        site = "https://festival-exemple.fr/"
        row = festival("festival-123", site)
        row["name"] = "Festival 123 2027"
        html = ('<header><img src="/logo-123-2027.jpg">'
                '<img src="/placeholder.png" data-src="/images/123-2027.jpg">'
                '<nav><img src="/poster-2027.jpg"></nav></header>'
                '<main><img data-original="/affiche-2027.png">'
                '<img hidden data-src="/hidden-123-2027.jpg">'
                '<img data-lazy-src="https://outside.example/123-2027.jpg"></main>')
        self.assertEqual(current_official_poster_candidates(html, site, row),
                         [site + "affiche-2027.png", site + "images/123-2027.jpg"])

    def test_poster_neutral_filename_can_use_own_editorial_metadata(self):
        from grossesondes_existing_official_updates import current_official_poster_candidates
        site = "https://festival-exemple.fr/"
        row = festival("festival-123", site)
        row["name"] = "Festival 123 2027"
        html = ('<main><img src="/a.jpg" alt="Affiche 2027">'
                '<img src="/b.png" title="Affiche Festival 123">'
                '<img src="/c.jpg" alt="Affiche 2026">'
                '<img src="/2026.jpg" alt="Affiche 2027">'
                '<img src="/d.jpg" alt="Logo Festival 123">'
                '<img src="/e.jpg" alt="Affiche">'
                '<img hidden src="/f.jpg" alt="Affiche 2027"></main>')
        self.assertEqual(current_official_poster_candidates(html, site, row),
                         [site + "a.jpg", site + "b.png"])

    def test_multivenue_homonym_uses_only_current_named_venue_address(self):
        from grossesondes_openagenda_linked_edition import PROFESSIONAL_PUBLIC_CONFIDENCE
        from grossesondes_existing_official_updates import multivenue_department_from_access
        site = "https://salle-exemple.fr/festival/"
        access = "https://salle-exemple.fr/infos-pratiques/"
        row = festival("festival-exemple-2027", site, dates=("2027-02-06","2027-02-07"))
        row.update(name="Festival Exemple : Une célébration 2027",
                   source=site, sourceConfidence=PROFESSIONAL_PUBLIC_CONFIDENCE,
                   city=None, department=None, venue=None)
        event = ("<nav><a href='/infos-pratiques/'>Infos pratiques</a></nav>"
                 "<main><h1>Festival Exemple : Une célébration</h1>"
                 "<p>Les 6 et 7 février 2027, le Festival Exemple investit 4 salles "
                 "de la ville de Colonne pour un festival post-punk. "
                 "Les artistes sont répartis entre les scènes de Salle des Rives, "
                 "du Bal du Port et du Théâtre.</p></main>")
        info = ("<main><h1>Infos pratiques</h1><h2>Salle des Rives</h2>"
                "<p>21 rue des Arts<br>39000 COLONNE</p></main>")
        self.assertEqual(multivenue_department_from_access(event, row, "Colonne",
            lambda _: info), ("39", access))
        for spelling in ("6 &amp; 7", "6, 7", "6-7"):
            self.assertEqual(multivenue_department_from_access(
                event.replace("6 et 7", spelling), row, "Colonne",
                lambda _: info), ("39", access), spelling)
        self.assertIsNone(multivenue_department_from_access(
            event.replace("6 et 7", "6 &amp; 8"), row, "Colonne",
            lambda _: info))

        for bad in (info.replace("Salle des Rives", "Bureau administratif"),
                    info.replace("COLONNE", "Autreville"),
                    info.replace("39000", "20000"),
                    info.replace("<p>21", "<p hidden>21"),
                    info.replace("<main>", "<footer>").replace("</main>", "</footer>")):
            self.assertIsNone(multivenue_department_from_access(event, row, "Colonne",
                lambda _: bad), bad)
        self.assertIsNone(multivenue_department_from_access(
            event.replace("Salle des Rives", "Autre salle"), row, "Colonne", lambda _: info))
        self.assertIsNone(multivenue_department_from_access(event,
            dict(row, sourceConfidence="unknown"), "Colonne", lambda _: info))
        calls = []
        def resolve(city, department):
            calls.append((city, department))
            if department is None:
                return None
            from official_admin_communes import search_url
            return {"city": "Colonne", "codeInsee": "39160", "lat": 47.1, "lon": 5.6,
                    "geoSource": search_url("Colonne")}
        original = doc(row)
        out, report = apply_independently_verified_updates(original, original, DAY,
            fetch={site: event, access: info}.__getitem__, limit=1, tick=0,
            commune_resolver=resolve)
        self.assertEqual(calls, [("Colonne", None), ("Colonne", "39")])
        updated = out["festivals"][0]
        self.assertTrue(updated["showOnMap"])
        self.assertIsNone(updated["venue"])
        self.assertIn(access, updated["auditSources"])
        self.assertTrue(_verified_official_update_delta(row, updated))

    def test_multivenue_named_contact_on_signed_event_page(self):
        from grossesondes_openagenda_linked_edition import PROFESSIONAL_PUBLIC_CONFIDENCE
        from grossesondes_existing_official_updates import multivenue_department_from_access
        site = "https://salle-exemple.fr/festival/"
        row = festival("festival-exemple-2027", site, dates=("2027-02-06","2027-02-07"))
        row.update(name="Festival Exemple : Une célébration 2027",
                   source=site, sourceConfidence=PROFESSIONAL_PUBLIC_CONFIDENCE,
                   city=None, department=None, venue=None)
        event = ("<main><h1>Festival Exemple : Une célébration</h1>"
                 "<p>Les 6 et 7 février 2027, le Festival Exemple investit 4 salles "
                 "de la ville de Colonne pour un festival post-punk. "
                 "Les artistes sont répartis entre les scènes de Salle des Rives, "
                 "du Bal du Port et du Théâtre.</p></main>")
        contact = ("<footer><h4>SALLE DES RIVES</h4>"
                   "<p>21 RUE DES ARTS<br>39000 COLONNE</p>"
                   "<h4>Newsletter</h4></footer>")
        def no_fetch(_):
            self.fail("The signed event page is already available")
        diagnostic = {}
        self.assertEqual(multivenue_department_from_access(
            event + contact, row, "Colonne", no_fetch,
            diagnostic=diagnostic), ("39", site))
        self.assertEqual(diagnostic["multivenue_postcode"],
                         "unique_named_venue_department")
        wrapped_event = event.replace("scènes de Salle des Rives",
                                      "scènes de\n <strong>Salle des Rives</strong>")
        wrapped_contact = contact.replace("SALLE DES RIVES",
                                          "\n SALLE <span>DES RIVES</span> \n")
        self.assertEqual(multivenue_department_from_access(
            wrapped_event + wrapped_contact, row, "Colonne", no_fetch,
            diagnostic=diagnostic), ("39", site))
        self.assertIsNone(multivenue_department_from_access(
            event + contact.replace("39000", "code inconnu"),
            row, "Colonne", no_fetch, diagnostic=diagnostic))
        self.assertEqual(diagnostic["multivenue_postcode"],
                         "named_venue_postcode_absent")
        for bad in (contact.replace("SALLE DES RIVES", "BUREAU ADMINISTRATIF"),
                    contact.replace("<p>21", "<p hidden>21"),
                    contact.replace("COLONNE", "AUTREVILLE"),
                    contact.replace("39000", "20000"),
                    contact.replace("<h4>SALLE DES RIVES</h4>",
                                    "<h4>SALLE DES RIVES</h4><h4>Autre lieu</h4>")):
            self.assertIsNone(multivenue_department_from_access(
                event + bad, row, "Colonne", no_fetch))
        conflict = ('<main><h2>Salle des Rives</h2>'
                    '<p>21 rue des Arts<br>93000 Colonne</p></main>')
        linked = event + "<a href='/infos-pratiques/'>Infos pratiques</a>" + contact
        self.assertIsNone(multivenue_department_from_access(
            linked, row, "Colonne", lambda _: conflict))

    def test_counted_inline_roster_and_stale_municipal_note(self):
        from grossesondes_openagenda_linked_edition import MUNICIPAL_PUBLIC_CONFIDENCE
        site = "https://agenda.example.org/evenement/festival-brume/"
        row = festival("festival-brume-2027", site)
        row.update(name="Festival Brume 2027", city="Exemple",
                   sourceConfidence=MUNICIPAL_PUBLIC_CONFIDENCE,
                   venue="Salle des Arts", geoPrecision="commune",
                   showOnMap=True, lat=48.1, lon=2.1,
                   notes=("Dates et genre revérifiés sur une fiche municipale officielle ; "
                          "salle confirmée, artistes à confirmer ; "
                          "repère indicatif au centre de la commune."))
        html = ("<article><h1>Festival Brume 2027</h1>"
                "<p>23 au 25 juillet 2027</p>"
                "<p><strong>UNE PROGRAMMATION DE FEU</strong></p>"
                "<p>Vous découvrirez quatres nouveaux groupes : "
                "<strong>Brume Noire, Rivages, Echo et Fracture</strong>.</p>"
                "</article>")
        self.assertEqual(listed_artists(page(html).relevant()),
                         ["Brume Noire", "Rivages", "Echo", "Fracture"])
        signed = doc(row)
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: html, limit=1, tick=0)
        updated = out["festivals"][0]
        self.assertEqual(updated["lineup"],
                         ["Brume Noire", "Rivages", "Echo", "Fracture"])
        self.assertEqual(updated["bands"], 4)
        self.assertIn("artistes annoncés sur la source officielle", updated["notes"])
        self.assertTrue(_verified_official_update_delta(row, updated))
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertEqual((updated["lat"], updated["lon"]), (48.1, 2.1))
        self.assertFalse(_verified_official_update_delta(
            row, dict(updated, notes="Information non prouvée")))
        for bad in (
                html.replace("quatres", "trois"),
                html.replace("Echo", "Rivages"),
                html.replace("Echo", "billetterie"),
                html.replace("Echo et Fracture", "Echo et Fracture ; ouverture des portes"),
                html.replace("<p>Vous", "<p hidden>Vous")):
            self.assertEqual(listed_artists(page(bad).relevant()), [])
        out, _ = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: html.replace("2027", "2028"),
            limit=1, tick=0)
        self.assertEqual(out["festivals"][0], row)

    def test_mozhell_official_news_updates_artists_and_price_without_secondary(self):
        row = festival("mozhell-open-air", MOZHELL)
        signed = doc(row)
        calls = []
        def fetch(url):
            calls.append(url)
            return {MOZHELL: HOME, ARTICLE: NEWS}[url]
        output, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=fetch, limit=1, tick=0)
        self.assertEqual(calls, [MOZHELL, ARTICLE])
        updated = output["festivals"][0]
        self.assertEqual(updated["lineup"], ["Ultra Vomit", "THE ARRS", "LocoMuerte"])
        self.assertEqual(updated["bands"], 3)
        self.assertIn("129,90 €", updated["price"])
        self.assertIn("billetterie officielle ouverte", updated["price"])
        self.assertEqual(updated["auditSources"], [MOZHELL, ARTICLE])
        self.assertTrue(_verified_official_update_delta(row, updated))
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertFalse(report["private_proposal_is_authority"])
        self.assertEqual(updated["showOnMap"], False)
        self.assertIsNone(updated["lat"])

    def test_isolated_browser_recovers_http_403_then_rechecks_real_official_news(self):
        row = festival("mozhell-open-air", MOZHELL)
        signed = doc(row)
        visited = []
        def fetch(url):
            visited.append(url)
            if url == MOZHELL:
                raise OSError("HTTP 403 SECRET_TOKEN_MUST_NOT_LEAK")
            return {ARTICLE: NEWS}[url]
        browser_urls = []
        def browser_fetch(url):
            browser_urls.append(url)
            return HOME
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=fetch, browser_fetch=browser_fetch,
            limit=1, tick=0)
        self.assertEqual(browser_urls, [MOZHELL])
        self.assertEqual(visited, [MOZHELL, ARTICLE])
        self.assertEqual(report["browser_recoveries"], 1)
        self.assertEqual(report["unavailable"], 0)
        self.assertEqual(out["festivals"][0]["lineup"],
                         ["Ultra Vomit", "THE ARRS", "LocoMuerte"])
        self.assertNotIn("SECRET_TOKEN_MUST_NOT_LEAK", str(report))

    def test_official_summer_ticket_city_proves_current_edition_not_winter(self):
        site = "https://festivalgueulesdebois.com/"
        link = site + "billet/"
        row = festival("les-gueules-de-bois-2027", site,
                       dates=("2027-08-19", "2027-08-21"))
        row.update(name="Les Gueules de Bois 2027", department="39")
        winter = ('<main><h1>Winter 2027 - 13 février 2027 à Légna</h1>'
                  '<a href="/billet/">Billetterie officielle</a></main>')
        summer = ('<html><head><title>Billetterie – Festival Les Gueules '
                  'de Bois – Été 2027</title></head><body><main>'
                  '<h1>Ton billet pour l’été</h1>'
                  '<p>Été 2027 · 19–21 août à Légna (Jura)</p>'
                  '</main></body></html>')
        self.assertEqual(current_official_ticket_city(summer, row), "Légna")
        self.assertIsNone(current_official_ticket_city(
            summer.replace("19–21 août", "13 février"), row))
        self.assertIsNone(current_official_ticket_city(winter, row))
        pages = {site: winter, link: summer}
        calls = []
        def browser(url):
            calls.append(url)
            return pages[url]
        def admin(city, department):
            self.assertEqual((city, department), ("Légna", "39"))
            return {"city": "Légna", "lat": 46.47, "lon": 5.64,
                    "codeInsee": "39000", "geoSource": "https://geo.api.gouv.fr/"}
        original = doc(row)
        out, report = apply_independently_verified_updates(
            original, original, DAY,
            fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")),
            browser_fetch=browser, commune_resolver=admin, limit=1, tick=0)
        self.assertEqual(calls, [site, link])
        self.assertEqual(out["festivals"][0]["city"], "Légna")
        self.assertTrue(out["festivals"][0]["showOnMap"])
        self.assertIn("les-gueules-de-bois-2027", report["accepted"])

    def test_direct_edition_daily_programme_can_gain_commune_marker(self):
        from grossesondes_first_party_direct_edition import PUBLISHED_CONFIDENCE
        site = "https://nocturnesauvage.fr/"
        ticket = site + "tickets/"
        row = festival("nocturne-sauvage-2026", site,
                       dates=("2026-12-01", "2026-12-06"))
        row.update(name="Nocturne Sauvage 2026", city="Toulouse",
                   department=None, sourceConfidence=PUBLISHED_CONFIDENCE)
        home = ("<h1>Festival Nocturne Sauvage</h1><p>Festival gothique</p>"
                "<a href='/tickets/'>Billetterie</a>"
                "<h2>mardi 1er décembre</h2><p>Expo le 1er décembre 2026</p>"
                "<h2>mercredi 2 décembre</h2><p>Concerts</p>"
                "<h2>jeudi 3 décembre</h2><p>Concerts</p>"
                "<h2>vendredi 4 décembre</h2><p>Concerts</p>"
                "<h2>samedi 5 décembre</h2><p>Concerts</p>"
                "<h2>dimanche 6 décembre</h2><p>Cinéma</p>")
        info = ("<h1>Billetteries – Tickets</h1>"
                "<p>Du 1er au 6 décembre 2026 - Toulouse</p>"
                "<footer>Nocturne Sauvage</footer>")
        admin_calls = []
        def admin(city, department):
            admin_calls.append((city, department))
            return {"city": city, "lat": 43.6, "lon": 1.44,
                    "codeInsee": "31555",
                    "geoSource": "https://geo.api.gouv.fr/communes?nom=Toulouse"}
        original = doc(row)
        out, report = apply_independently_verified_updates(
            original, original, "2026-11-26", limit=1, tick=0,
            fetch=lambda url: {site: home, ticket: info}[url],
            commune_resolver=admin)
        self.assertEqual(admin_calls, [("Toulouse", None)])
        self.assertTrue(out["festivals"][0]["showOnMap"])
        self.assertEqual(out["festivals"][0]["geoPrecision"], "commune")
        self.assertIn(row["slug"], report["accepted"])
        self.assertTrue(_verified_official_update_delta(row, out["festivals"][0]))
        for bad in (info.replace("1er au 6", "2 au 5"),
                    info.replace("Toulouse", "Bordeaux"),
                    info + "<p>Festival annulé</p>"):
            admin_calls.clear()
            out, _ = apply_independently_verified_updates(
                original, original, "2026-11-26", limit=1, tick=0,
                fetch=lambda url: {site: home, ticket: bad}[url],
                commune_resolver=admin)
            self.assertFalse(out["festivals"][0]["showOnMap"])
            self.assertEqual(admin_calls, [])

    def test_year_before_dates_title_and_visible_current_locality_map(self):
        from future_city_preflight import exact_edition_city
        site = "https://festival-exemple.fr/"
        row = festival("festival-foudre-libre-2027", site,
                       dates=("2027-08-19", "2027-08-21"))
        row.update(name="Festival Foudre Libre 2027", department=None)
        html = ('<html><head><title>Festival Foudre Libre – Été 2027 · '
                '19, 20 et 21 août à Légna (39)</title></head>'
                '<body><main><h2>Été 2027</h2>'
                '<p>19, 20 &amp; 21 AOÛT 2027</p><p>Légna (39) · Jura</p>'
                '<h2>Hiver 2027</h2><p>13 février à Autreville</p>'
                '</main><footer>Été 2027 · 19–21 août à Légna (Jura)</footer>'
                '</body></html>')
        self.assertEqual(exact_edition_city(html, row)["city"], "Légna")
        for bad in (
            html.replace("19, 20 et 21", "19 et 21"),
            html.replace("19, 20 et 21", "19, 20 et 22"),
            html.replace("Légna", "Autreville", 1),
            html.replace("2027", "2026"),
        ):
            self.assertIsNone(exact_edition_city(bad, row))
        original = doc(row)
        def admin(city, department):
            self.assertEqual((city, department), ("Légna", None))
            return {"city": city, "lat": 46.47, "lon": 5.64,
                    "codeInsee": "39000", "geoSource": "https://geo.api.gouv.fr/communes?nom=L%C3%A9gna"}
        out, report = apply_independently_verified_updates(
            original, original, DAY,
            fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")),
            browser_fetch=lambda _: html, commune_resolver=admin, limit=1, tick=0)
        self.assertEqual(out["festivals"][0]["city"], "Légna")
        self.assertTrue(out["festivals"][0]["showOnMap"])
        self.assertIn(row["slug"], report["accepted"])
        self.assertTrue(_verified_official_update_delta(row, out["festivals"][0]))
        invalid = deepcopy(out["festivals"][0])
        invalid["geoSource"] = "https://geo.api.gouv.fr/"
        self.assertFalse(_verified_official_update_delta(row, invalid))

    def test_first_names_section_bound_to_exact_season_and_dates(self):
        from grossesondes_existing_official_updates import season_scoped_first_names
        site = "https://festival-exemple.fr/"
        row = festival("festival-foudre-libre-2027", site,
                       dates=("2027-08-19", "2027-08-21"))
        row.update(name="Festival Foudre Libre 2027", department="39")
        # Adapted semantic structure of a real first-party homepage:
        # separate seasonal labels, figcaption roster, history and ticket list.
        html = (
            '<html><head><title>Festival Foudre Libre – Été 2027 · '
            '19, 20 et 21 août à Légna (39)</title></head><body>'
            '<nav><p>Été 2027</p><h3>Les premiers noms.</h3>'
            '<ul><li>Navigation</li></ul></nav>'
            '<main><h2>Festival Foudre Libre 2027</h2>'
            '<p>19, 20 &amp; 21 AOÛT 2027</p><p>Légna (39) · Jura</p>'
            '<figure><figcaption><p>Été 2027</p>'
            '<h3>Les premiers noms.</h3><ul>'
            '<li><a>Foudre Noire ↗</a></li><li>Brume Rouge</li>'
            '<li>Ombre Vive</li></ul></figcaption></figure>'
            '<h2>Billetterie</h2><ul><li>Camping</li></ul>'
            '<p>Hiver 2027</p><h3>Les premiers noms.</h3>'
            '<ul><li>Artiste Hivernal</li></ul>'
            '<p>Été 2026</p><h3>Les premiers noms.</h3>'
            '<ul><li>Ancien Artiste</li></ul></main></body></html>')
        expected = ["Foudre Noire", "Brume Rouge", "Ombre Vive"]
        self.assertEqual(season_scoped_first_names(page(html), html, row, DAY),
                         expected)
        for bad in (
            html.replace("19, 20 et 21", "19, 20 et 22"),
            html.replace("<figcaption><p>Été 2027</p>",
                         "<figcaption><p>Hiver 2027</p>"),
            html.replace("<figcaption><p>Été 2027</p>",
                         "<figcaption><p>Été 2026</p>"),
        ):
            self.assertEqual(season_scoped_first_names(page(bad), bad, row, DAY),
                             [])
        original = doc(row)
        out, report = apply_independently_verified_updates(
            original, original, DAY,
            fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")),
            browser_fetch=lambda _: html, commune_resolver=lambda *_: None,
            limit=1, tick=0)
        updated = out["festivals"][0]
        self.assertEqual(updated["lineup"], expected)
        self.assertEqual(updated["bands"], 3)
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertTrue(_verified_official_update_delta(row, updated))

    def test_split_title_description_visible_city_and_roster(self):
        from future_city_preflight import current_edition_description, exact_edition_city
        from grossesondes_existing_official_updates import season_scoped_first_names
        site = "https://festival-exemple.fr/"
        row = festival("festival-foudre-libre-2027", site,
                       dates=("2027-08-19", "2027-08-21"))
        row.update(name="Festival Foudre Libre 2027", department=None)
        html = (
            '<html><head><title>Festival Foudre Libre</title>'
            '<meta property="og:description" content="Été 2027 · '
            '19, 20 et 21 août à Légna (39)"></head><body>'
            '<main><section><p>7e édition</p><h2>Et cet été</h2>'
            '<p>19, 20 &amp; 21 AOÛT 2027<br/>Légna (39) · Jura</p>'
            '<figure><figcaption><p>Été 2027</p>'
            '<h3>Les premiers noms.</h3><ul><li>Brume Noire</li>'
            '<li>Foudre Rouge</li></ul></figcaption></figure></section>'
            '<section><p>Hiver 2027</p><h3>Les premiers noms.</h3>'
            '<ul><li>Autre Artiste</li></ul></section></main></body></html>')
        self.assertEqual(current_edition_description(html, row),
                         {"city": "Légna", "season": "ete", "year": 2027})
        self.assertEqual(exact_edition_city(html, row)["city"], "Légna")
        self.assertEqual(season_scoped_first_names(page(html), html, row, DAY),
                         ["Brume Noire", "Foudre Rouge"])
        for bad in (
            html.replace("21 AOÛT 2027", "22 AOÛT 2027"),
            html.replace("<br/>Légna (39)", "</p><p>Légna (39)"),
            html.replace("<br/>Légna (39)", "<br/>Légna (01)"),
            html.replace("<title>Festival Foudre Libre", "<title>Autre Festival"),
            html.replace("</head>", '<meta name="description" content="Hiver 2027 · '
                         '13 février à Légna (39)"></head>'),
        ):
            self.assertIsNone(current_edition_description(bad, row))
            self.assertEqual(season_scoped_first_names(page(bad), bad, row, DAY), [])
        original = doc(row)
        def admin(city, department):
            return {"city": city, "lat": 46.47, "lon": 5.64,
                    "codeInsee": "39000",
                    "geoSource": "https://geo.api.gouv.fr/communes?nom=L%C3%A9gna"}
        out, report = apply_independently_verified_updates(
            original, original, DAY,
            fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")),
            browser_fetch=lambda _: html, commune_resolver=admin,
            limit=1, tick=0)
        updated = out["festivals"][0]
        self.assertEqual(updated["city"], "Légna")
        self.assertTrue(updated["showOnMap"])
        self.assertEqual(updated["lineup"], ["Brume Noire", "Foudre Rouge"])
        self.assertTrue(_verified_official_update_delta(row, updated))
        self.assertEqual(report["accepted"], [row["slug"]])

    def test_seasonal_ticket_cards_preserve_price_tiers_and_status(self):
        from grossesondes_existing_official_updates import (
            seasonal_ticket_card_offers, seasonal_ticket_summary,
        )
        site = "https://festival-exemple.fr/"
        row = festival("festival-foudre-libre-2027", site,
                       dates=("2027-08-19", "2027-08-21"))
        row.update(name="Festival Foudre Libre 2027", department="39")
        html = (
            '<html><head><title>Festival Foudre Libre</title>'
            '<meta property="og:description" content="Été 2027 · '
            '19, 20 et 21 août à Légna (39)"></head><body><main>'
            '<section><p>19, 20 &amp; 21 AOÛT 2027<br/>Légna (39) · Jura</p></section>'
            '<section><p>Billetterie · Été 2027</p><h2>Choisis ton pass.</h2><ul>'
            '<li><img alt="Pass 3 jours Tarif réduit : 89 €."><p>Festival</p>'
            '<h3>Tarif réduit</h3><p>Disponibilité : Épuisé</p></li>'
            '<li><img alt="Pass 3 jours Plein tarif : 115 €."><p>Festival</p>'
            '<h3>Pass 3 jours · Plein tarif</h3><p>Disponibilité : Disponible</p></li>'
            '<li><img alt="Pass 3 jours Soutien : 130 €."><p>Festival</p>'
            '<h3>Tarif soutien</h3><p>Disponibilité : Disponible</p></li>'
            '<li><p>Camping</p><h3>Aire de bivouac</h3><p>Gratuit</p></li>'
            '</ul></section><section><p>Billetterie · Hiver 2027</p><ul>'
            '<li><img alt="Pass 1 jour Hiver : 35 €"><p>Festival</p>'
            '<h3>Hiver</h3><p>Disponibilité : Disponible</p></li>'
            '</ul></section></main></body></html>')
        offers = seasonal_ticket_card_offers(html, row, DAY)
        self.assertEqual(len(offers), 3)
        self.assertEqual(offers[(3, "tarif reduit")], ("Tarif réduit", "89 €", "épuisé"))
        self.assertEqual(offers[(3, "plein tarif")], ("Plein tarif", "115 €", "disponible"))
        summary = seasonal_ticket_summary(offers)
        self.assertIn("130 € (disponible)", summary)
        self.assertIn("89 € (épuisé)", summary)
        self.assertNotIn("35 €", summary)
        for bad in (
            html.replace("Disponibilité : Épuisé", "Disponibilité : Actualisation…"),
            html.replace('alt="Pass 3 jours Tarif réduit', 'hidden alt="Pass 3 jours Tarif réduit'),
            html.replace("Pass 3 jours Soutien", "Pass 3 jours Autre formule"),
            html.replace("Billetterie · Été 2027", "Billetterie · Été 2026"),
            html.replace("21 AOÛT 2027", "22 AOÛT 2027"),
            html.replace("115 €.", "115 €.").replace(
                "Disponibilité : Disponible</p></li><li><img alt=\"Pass 3 jours Soutien",
                "Disponibilité : Épuisé</p><p>Disponibilité : Disponible</p></li><li><img alt=\"Pass 3 jours Soutien"),
        ):
            self.assertEqual(seasonal_ticket_card_offers(bad, row, DAY), {})
        self.assertIn("formules affichées épuisées", seasonal_ticket_summary({
            (3, "tarif reduit"): ("Tarif réduit", "89 €", "épuisé")}))
        original = doc(row)
        out, report = apply_independently_verified_updates(
            original, original, DAY,
            fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")),
            browser_fetch=lambda _: html, commune_resolver=lambda *_: None,
            limit=1, tick=0)
        updated = out["festivals"][0]
        self.assertEqual(updated["price"], summary)
        self.assertTrue(_verified_official_update_delta(row, updated))
        self.assertEqual(report["accepted"], [row["slug"]])

        # A previously published canonical set must refresh both amounts and
        # availability, including exhaustion of every displayed paid tier.
        sold_out = html.replace("Disponibilité : Disponible", "Disponibilité : Épuisé")
        sold_out = sold_out.replace("115 €.", "119 €.")
        sold_doc, sold_report = apply_independently_verified_updates(
            out, out, DAY, fetch=lambda _: sold_out,
            commune_resolver=lambda *_: None, limit=1, tick=0)
        sold = sold_doc["festivals"][0]
        self.assertIn("119 € (épuisé)", sold["price"])
        self.assertIn("formules affichées épuisées", sold["price"])
        self.assertNotIn("billetterie officielle ouverte", sold["price"])
        self.assertTrue(_verified_official_update_delta(updated, sold))
        self.assertEqual(sold_report["accepted"], [row["slug"]])
        # A disappeared card is not proof of a removed or sold-out tier.
        incomplete = sold_out.replace(
            '<li><img alt="Pass 3 jours Soutien : 130 €."><p>Festival</p>'
            '<h3>Tarif soutien</h3><p>Disponibilité : Épuisé</p></li>', '')
        self.assertNotEqual(incomplete, sold_out)
        result, _ = apply_independently_verified_updates(
            sold_doc, sold_doc, DAY, fetch=lambda _: incomplete,
            commune_resolver=lambda *_: None, limit=1, tick=0)
        self.assertEqual(result["festivals"][0]["price"], sold["price"])

        # A raw response with valid edition identity but all statuses still
        # loading must not suppress the independently rendered same-root DOM.
        pending = html.replace("Disponibilité : Épuisé", "Disponibilité : Actualisation…").replace(
            "Disponibilité : Disponible", "Disponibilité : Actualisation…")
        out, report = apply_independently_verified_updates(
            original, original, DAY, fetch=lambda _: pending,
            browser_fetch=lambda _: html, browser_sites=(site,),
            commune_resolver=lambda *_: None, limit=1, tick=0)
        self.assertEqual(out["festivals"][0]["price"], summary)
        self.assertTrue(_verified_official_update_delta(row, out["festivals"][0]))
        diagnostic = report["official_edition_diagnostics"][0]
        self.assertTrue(diagnostic["seasonal_ticket_rendered_proof"])
        self.assertEqual(diagnostic["seasonal_ticket_tiers_found"], 3)
        self.assertEqual(diagnostic["commune_diagnostic"],
                         "admin_resolution_unavailable_or_ambiguous")
        # An explicit competing raw status is not merely a loading screen.
        mixed = pending.replace("Disponibilité : Actualisation…",
                                "Disponibilité : Épuisé", 1)
        for raw, allowed in ((mixed, (site,)), (pending, ())):
            out, report = apply_independently_verified_updates(
                original, original, DAY, fetch=lambda _: raw,
                browser_fetch=lambda _: html, browser_sites=allowed,
                commune_resolver=lambda *_: None, limit=1, tick=0)
            self.assertIsNone(out["festivals"][0]["price"])
            self.assertFalse(report["official_edition_diagnostics"][0]
                             ["seasonal_ticket_rendered_proof"])


    def test_linked_official_news_can_recover_when_both_raw_requests_fail(self):
        signed = doc(festival("mozhell-open-air", MOZHELL))
        browser_calls = []
        def blocked(_):
            raise OSError("HTTP 403")
        def browser(url):
            browser_calls.append(url)
            return {MOZHELL: HOME, ARTICLE: NEWS}[url]
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=blocked, browser_fetch=browser,
            limit=1, tick=0)
        self.assertEqual(browser_calls, [MOZHELL, ARTICLE])
        self.assertEqual(out["festivals"][0]["lineup"],
                         ["Ultra Vomit", "THE ARRS", "LocoMuerte"])
        self.assertEqual(report["browser_recoveries"], 1)
        self.assertEqual(report["unavailable"], 0)

    def test_isolated_browser_wrong_edition_cannot_modify_signed_row(self):
        row = festival("mozhell-open-air", MOZHELL)
        signed = doc(row)
        def fail(_):
            raise OSError("HTTP 403")
        fake = HOME.replace("2027", "2026").replace("25 juillet", "25 mars")
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=fail, browser_fetch=lambda _: fake,
            limit=1, tick=0)
        self.assertEqual(out, signed)
        self.assertEqual(report["browser_recoveries"], 1)
        self.assertEqual(report["accepted"], [])

    def test_prevalidated_ticket_status_and_new_prices_are_composable(self):
        # Reproduces the actual Motocultor Publisher order: a separately
        # validated ticket-availability update precedes the current official
        # price recheck on the same signed edition.
        row = festival(
            "motocultor-festival", MOTO,
            dates=("2027-08-19", "2027-08-22"),
            lineup=["Helloween", "Halestorm"],
            price="Pass 1 jour : 82 € — billetterie officielle ouverte")
        row["name"] = "Motocultor Festival"
        signed = doc(row)
        intermediate = deepcopy(signed)
        intermediate["festivals"][0]["ticketAvailability"] = {
            "source": MOTO, "verifiedAt": DAY,
            "scope": "per_category_only", "categories": [
                {"name": "Pass 1 jour", "status": "in_stock"},
                {"name": "Pass 4 jours", "status": "in_stock"}]}
        official_home = (
            "<main><h1>Motocultor Festival 2027</h1>"
            "<p>Carhaix, du 19 au 22 août 2027.</p>"
            "<section><ul><li><h3>Pass 4 jours</h3><p>Les quatre "
            "jours du festival.</p><ol><li>Tarif normal239 €En vente"
            "</li></ol></li><li><h3>Pass 1 jour</h3>"
            "<p>Choisissez votre journée.</p>"
            "<ol><li>Journée au choix82 €En vente</li></ol>"
            "</li></ul></section>"
            "<article><p>Les Pass 4J Early Birds sont SOLD OUT ; "
            "le Pass 4J passe au tarif normal de 239 € hors frais, "
            "et les Pass 1J restent en vente.</p></article></main>")
        out, report = apply_independently_verified_updates(
            intermediate, signed, DAY, fetch=lambda _: official_home,
            limit=1, tick=0)
        value = out["festivals"][0]
        self.assertEqual(value["ticketAvailability"],
                         intermediate["festivals"][0]["ticketAvailability"])
        self.assertIn("Pass 4 jours : 239 €", value["price"])
        self.assertIn("Pass 1 jour : 82 €", value["price"])
        self.assertEqual(report["accepted"], ["motocultor-festival"])
        # The official delta is valid ONLY relative to the prior stage.
        # A combined signed-row delta is deliberately NOT accepted as a
        # single unqualified official update.
        self.assertTrue(_verified_official_update_delta(
            intermediate["festivals"][0], value))
        self.assertFalse(_verified_official_update_delta(row, value))

        # Other pre-mutated fields are not admissible to the official scan.
        altered = deepcopy(intermediate)
        altered["festivals"][0]["lineup"].append("unverified private artist")
        unchanged, held = apply_independently_verified_updates(
            altered, signed, DAY, fetch=lambda _: official_home,
            limit=1, tick=0)
        self.assertEqual(unchanged, altered)
        self.assertEqual(held["official_edition_diagnostics"][0]["reason"],
                         "different_from_current_signed_edition")

    def test_official_host_diagnostics_do_not_leak_fetch_errors(self):
        import json
        row = festival("mozhell-open-air", MOZHELL)
        signed = doc(row)
        def forbidden_fetch(_url):
            raise ValueError("UNTRUSTED_PRIVATE_MESSAGE_DO_NOT_LOG")
        target, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=forbidden_fetch, limit=1, tick=0)
        self.assertEqual(target, signed)
        self.assertEqual(report["checked_official_hosts"], 1)
        self.assertEqual(report["checked_official_sources"], [MOZHELL])
        self.assertEqual(report["unavailable"], 1)
        self.assertEqual(report["unavailable_official_sources"],
                         [{"url": MOZHELL, "error_type": "ValueError"}])
        self.assertNotIn("UNTRUSTED_PRIVATE_MESSAGE_DO_NOT_LOG",
                         json.dumps(report))

    def test_official_scan_explains_no_changed_fields_without_mutating_catalogue(self):
        row = festival("mozhell-open-air", MOZHELL)
        signed = doc(row)
        home = "<main><h1>mozhell-open-air 2027</h1><p>Infos festival 2027</p></main>"
        target, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: home, limit=1, tick=0)
        self.assertEqual(target, signed)
        self.assertEqual(report["unavailable_official_sources"], [])
        self.assertEqual(report["checked_official_sources"], [MOZHELL])
        self.assertEqual(report["official_edition_diagnostics"][0]["slug"],
                         row["slug"])
        self.assertTrue(report["official_edition_diagnostics"][0][
            "homepage_matches_signed_edition"])
        self.assertEqual(report["official_edition_diagnostics"][0]["reason"],
                         "no_changed_fields_from_official_evidence")

    def test_current_official_lineup_location_heading_and_tickets(self):
        # A current-edition homepage may group artists beneath
        # "Ils seront à Carhaix" without a "groupes annoncés" heading.
        # The complete 2027 edition identity is independently checked.
        row = festival(
            "motocultor-festival", MOTO,
            dates=("2027-08-19", "2027-08-22"),
            lineup=["Helloween", "Halestorm"],
            price="Pass 4 jours : 228 € (Early Bird 3)")
        home = (
            "<main><p>Du jeudi 19 au dimanche 22 août 2027</p>"
            "<h2>Ils seront à Carhaix</h2><ul>"
            "<li>Helloween</li><li>Alestorm</li>"
            "<li>Cavalera Chaos A.D.</li><li>VCTMS</li>"
            "<li>Alestorm</li><li>+ 12 groupes à confirmer</li>"
            "</ul><h3>Pass 4 jours</h3>"
            "<p>Tarif normal 239 € en vente</p>"
            "<h3>Pass 1 jour</h3><p>82 € en vente</p>"
            "<p>Motocultor Festival 2027</p></main>")
        signed = doc(row)
        updated, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: home, limit=1, tick=0)
        festival_2027 = updated["festivals"][0]
        self.assertEqual(
            festival_2027["lineup"],
            ["Helloween", "Halestorm", "Alestorm",
             "Cavalera Chaos A.D.", "VCTMS"])
        self.assertEqual(festival_2027["bands"], 5)
        self.assertIn("239 €", festival_2027["price"])
        self.assertIn("82 €", festival_2027["price"])
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertTrue(_verified_official_update_delta(row, festival_2027))

        # A current-year page cannot serve as proof for next year's edition.
        old_home = home.replace("2027", "2026")
        untouched, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: old_home, limit=1, tick=0)
        self.assertEqual(untouched["festivals"][0], row)
        self.assertEqual(report["accepted"], [])

    def test_cloud_scan_rotation_ignores_pr_only_run_numbers(self):
        # 48 signed official hosts must be covered by the two daily
        # publisher scans regardless of any intervening CI-only PR runs.
        from datetime import date
        yml = (Path(__file__).resolve().parents[1] /
               ".github/workflows/grossesondes-cloud-sync.yml"
               ).read_text(encoding="utf-8")
        self.assertNotIn("GROSSES_ONDES_OFFICIAL_UPDATE_RUN:", yml)
        self.assertIn("cron: '47 10 * * *'", yml)
        self.assertIn("cron: '45 17 * * *'", yml)
        hosts = [festival(f"festival-{i:02d}",
                          f"https://festival-{i:02d}.fr/")
                 for i in range(48)]
        published = doc(*hosts)
        morning = date.fromisoformat(DAY).toordinal() * 2
        first = {url for url, _ in signed_rotation(
            published, DAY, limit=24, tick=morning)}
        second = {url for url, _ in signed_rotation(
            published, DAY, limit=24, tick=morning + 1)}
        self.assertEqual(len(first), 24)
        self.assertEqual(len(second), 24)
        self.assertFalse(first & second)
        self.assertEqual(len(first | second), 48)

    def test_motocultor_real_format_from_official_article(self):
        row = festival("motocultor", MOTO,
                       dates=("2027-08-19", "2027-08-22"),
                       lineup=["Helloween", "Halestorm"])
        signed = doc(row)
        result, report = apply_independently_verified_updates(
            signed, signed, DAY, limit=1, tick=0,
            fetch=lambda u: {MOTO: MOTO_HOME, MOTO_NEWS: MOTO_ARTICLE}[u])
        names = result["festivals"][0]["lineup"]
        self.assertIn("Alestorm", names)
        self.assertIn("Flotsam & Jetsam", names)
        self.assertIn("Les Bâtards du Roi", names)
        self.assertIn("VCTMS", names)
        self.assertEqual(len(names), 23)
        self.assertEqual(report["accepted_changes"][0]["artists_added"], 21)

    def test_image_only_edition_h1_proves_signed_motocultor_2027(self):
        # Real Astro homepage: the hero H1 contains ONLY the edition logo
        # image. The accessible alt is the visible name/year; date and ticket
        # details are ordinary HTML. News <article> cards compete for scope.
        home = (
            "<main><header><h1 class='hero__logo'>"
            "<img alt='Motocultor Festival 2027' src='/logo.webp'></h1>"
            "<p>Du jeudi 19 au dimanche 22 août 2027</p></header>"
            "<h2>Ils seront à Carhaix</h2><ul><li>Helloween</li>"
            "<li>Halestorm</li></ul>"
            "<h2>Billetterie</h2>"
            "<h3>Pass 4 jours</h3>"
            "<p>Les quatre jours du festival.</p>"
            "<ol><li><span>Tarif normal</span>"
            "<span>239 €</span><span>En vente</span></li></ol>"
            "<h3>Pass 1 jour</h3>"
            "<p>Choisissez votre journée.</p>"
            "<ol><li><span>Journée au choix</span>"
            "<span>82 €</span><span>En vente</span></li></ol>"
            "<article><h3><a href='/actualites/21-nouveaux-groupes/'>"
            "21 nouveaux noms rejoignent l'affiche !</a></h3></article>"
            "</main>")
        row = festival("motocultor-festival", MOTO,
                       dates=("2027-08-19", "2027-08-22"),
                       lineup=["Helloween", "Halestorm"],
                       price="Pass 4 jours : 228 € (Early Bird 3)")
        row["name"] = "Motocultor Festival"  # public signed row lacks year
        signed = doc(row)
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, limit=1, tick=0,
            fetch=lambda u: {MOTO: home, MOTO_NEWS: MOTO_ARTICLE}[u])
        updated = out["festivals"][0]
        self.assertEqual(report["accepted"], ["motocultor-festival"])
        self.assertEqual(updated["bands"], 23)
        self.assertIn("Alestorm", updated["lineup"])
        self.assertIn("VCTMS", updated["lineup"])
        self.assertIn("239 €", updated["price"])
        self.assertIn("82 €", updated["price"])
        self.assertTrue(_verified_official_update_delta(row, updated))

    def test_only_accessible_visible_heading_logo_can_identify_edition(self):
        parsed = page(
            "<main><h1><img alt='Motocultor Festival 2027' "
            "src='/signed.webp'></h1><p>19 au 22 août 2027</p></main>")
        self.assertTrue(any(b["tag"] == "h1" and
                            b["text"] == "Motocultor Festival 2027"
                            for b in parsed.blocks))
        # Non-heading logo and hidden image cannot authenticate an edition.
        ignored = page(
            "<main><img alt='Motocultor Festival 2027' src='/other.webp'>"
            "<h1>Événement annoncé</h1>"
            "<span aria-hidden='true'>"
            "<img alt='Motocultor Festival 2027' src='/hidden.webp'>"
            "</span><p>19 au 22 août 2027</p></main>")
        self.assertFalse(any("Motocultor Festival 2027" in b["text"]
                             for b in ignored.blocks))

    def test_no_artist_count_ceiling_for_a_verified_official_roster(self):
        # A real festival can confirm >60 groups on its own official page.
        # The HTML, source, edition and individual names remain validated.
        row = festival("mozhell-open-air", MOZHELL)
        announced = [f"Artist {i:03d}" for i in range(1, 76)]
        official = (
            "<main><h1>MozHell Open Air 2027</h1>"
            "<h2>Groupes annoncés</h2><ul>" +
            "".join(f"<li>{name}</li>" for name in announced) +
            "</ul></main>"
        )
        signed = doc(row)
        result, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda url: official, limit=1, tick=0)
        new = result["festivals"][0]
        self.assertEqual(new["lineup"], announced)
        self.assertEqual(new["bands"], 75)
        self.assertTrue(_verified_official_update_delta(row, new))
        self.assertEqual(report["accepted"], ["mozhell-open-air"])

    def test_motocultor_homepage_news_cards_do_not_hide_main_ticket_prices(self):
        # Public homepage mixes historic news <article> cards with 2027
        # programming and ticket categories in <main>.
        home = (MOTO_HOME.replace("</main>", (
            "<h3>Pass 4 jours</h3><p>Tarif normal 239 € en vente</p>"
            "<h3>Pass 1 jour</h3><p>Journée au choix 82 € en vente</p>"
            "</main>")) +
            "<article><p>Dernières actualités : édition 2026</p></article>")
        row = festival(
            "motocultor-festival", MOTO,
            dates=("2027-08-19", "2027-08-22"),
            lineup=["Helloween", "Halestorm"],
            price="Pass 4 jours : 228 € (Early Bird 3)")
        signed = doc(row)
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, limit=1, tick=0,
            fetch=lambda url: {MOTO: home, MOTO_NEWS: MOTO_ARTICLE}[url])
        updated = out["festivals"][0]
        self.assertEqual(updated["bands"], 23)
        self.assertIn("Alestorm", updated["lineup"])
        self.assertIn("239 €", updated["price"])
        self.assertIn("82 €", updated["price"])
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertTrue(_verified_official_update_delta(row, updated))

    def test_motocultor_real_layout_header_outside_main_news_inside_main(self):
        # Real signed homepage composition: the 2027 logo is in a header,
        # ticket cards in main, and archival 2026 articles inside main.
        # Exactly one John Bush act, despite two historical billings.
        long_billing = "John Bush celebrating the songs of Anthrax, 1993-2003"
        home = (
            "<header><h1><img alt='Motocultor Festival 2027' "
            "src='/current.webp'></h1>"
            "<p>Du jeudi 19 au dimanche 22 août 2027</p></header>"
            "<main><section><h2>Ils seront à Carhaix</h2><ul>"
            "<li>Helloween</li><li>John Bush "
            "celebrating the songs of Anthrax, 1993-2003</li></ul></section>"
            "<section><h2>Billetterie</h2><ul><li><h3>Pass 4 jours</h3>"
            "<p>Les quatre jours du festival</p><ol>"
            "<li>Tarif normal 239 € En vente</li></ol></li>"
            "<li><h3>Pass 1 jour</h3><ol>"
            "<li>Journée au choix 82 € En vente</li></ol></li></ul></section>"
            "<article><h3>Souvenirs 2026</h3>"
            "<p>Ancienne édition 2026 en images</p></article></main>"
        )
        row = festival("motocultor-festival", MOTO,
                       dates=("2027-08-19", "2027-08-22"),
                       lineup=["Helloween", "John Bush", long_billing],
                       price="Pass 4 jours : 228 € (Early Bird 3)")
        row["name"] = "Motocultor Festival"
        signed = doc(row)
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, limit=1, tick=0,
            fetch=lambda _: home)
        updated = out["festivals"][0]
        self.assertEqual(updated["lineup"], ["Helloween", long_billing])
        self.assertEqual(updated["bands"], 2)
        self.assertIn("239 €", updated["price"])
        self.assertIn("82 €", updated["price"])
        self.assertEqual(report["accepted"], ["motocultor-festival"])
        self.assertTrue(_verified_official_update_delta(row, updated))
        tampered = deepcopy(updated)
        tampered["lineup"] = ["Helloween"]
        tampered["bands"] = 1
        self.assertFalse(_verified_official_update_delta(row, tampered))

    def test_live_pass_card_ignores_sold_out_earlier_tier(self):
        # The real festival site now advertises the regular 4-day pass at
        # 239 euros, despite three older Early Bird tiers being sold out.
        # A nested LI card can contain both words "épuisé" and "en vente".
        home = (
            "<header><h1>Motocultor Festival 2027</h1>"
            "<p>19 au 22 août 2027</p></header>"
            "<main><section><ul>"
            "<li><h3>Pass 4 jours</h3>"
            "<p>Early Bird 3 : 228 € Épuisé</p>"
            "<p>Tarif normal 239 € En vente</p>"
            "<p>Hors frais de location</p></li>"
            "<li><h3>Pass 1 jour</h3>"
            "<p>Journée au choix 82 € En vente</p></li>"
            "</ul></section>"
            "<article><h3>Pass 4 jours Early Birds SOLD OUT</h3>"
            "<p>L'ancienne offre est épuisée</p></article></main>"
        )
        clean = page(home)
        available = advertised_passes([
            b for b in clean.blocks if b["scope"] == "main"])
        self.assertEqual(available, {4: "239 €", 1: "82 €"})
        row = festival(
            "motocultor-festival", MOTO,
            dates=("2027-08-19", "2027-08-22"),
            lineup=["Helloween"],
            price="Pass 4 jours : 228 € (Early Bird 3)")
        row["name"] = "Motocultor Festival"
        updated, report = apply_independently_verified_updates(
            doc(row), doc(row), DAY, limit=1, tick=0,
            fetch=lambda _: home)
        self.assertEqual(report["accepted"], [row["slug"]])
        self.assertEqual(
            updated["festivals"][0]["price"],
            "Pass 4 jours : 239 € ; Pass 1 jour : 82 €"
            " — billetterie officielle ouverte")
        self.assertTrue(_verified_official_update_delta(
            row, updated["festivals"][0]))

        sold_out = (
            "<main><h1>Motocultor Festival 2027</h1>"
            "<li><h3>Pass 4 jours</h3>"
            "<p>Tarif normal 239 € Épuisé</p></li></main>")
        self.assertEqual(advertised_passes(page(sold_out).relevant()), {})

    def test_official_4j_normal_price_after_sold_out_early_bird(self):
        # Reproduces the current 21-Nov first-party announcement: "Pass 4J"
        # is the shorthand for pass 4 jours. The *Early Bird* tiers were
        # sold out; the currently available normal pass costs 239 €.
        news = (
            "<main><article>"
            "<h1>Les Pass 4J Early Birds sont SOLD OUT !</h1>"
            "<p>Motocultor Festival 2027, 19 au 22 août à Carhaix.</p>"
            "<h2>Le Pass 4J passe au tarif normal</h2>"
            "<p>Après l'épuisement des trois paliers d'Early Birds, "
            "le Pass 4J est désormais disponible au tarif normal "
            "de 239 € (hors frais de location).</p>"
            "<p>Les Pass 1J sont également disponibles à la vente "
            "depuis une semaine.</p></article></main>"
        )
        found = advertised_passes(page(news).relevant())
        self.assertEqual(found, {4: "239 €"})
        self.assertEqual(
            advertised_passes(page(
                "<article><h2>Les Pass 4J Early Birds sont SOLD OUT !</h2>"
                "<p>Ancien palier 228 € épuisé.</p></article>"
            ).relevant()), {})

        home = (
            MOTO_HOME.replace("</main>",
                "<section><h3>Pass 1 jour</h3>"
                "<p>Journée au choix 82 € en vente</p></section>"
                "<a href='/actualites/early-birds-epuises/'>"
                "Pass 4J tarif normal annoncé</a></main>")
        )
        ticket_url = "https://www.motocultor-festival.com/actualites/early-birds-epuises/"
        row = festival("motocultor-festival", MOTO,
                       dates=("2027-08-19", "2027-08-22"),
                       lineup=["Helloween"],
                       price="Pass 4 jours : 228 € (Early Bird 3)")
        row["name"] = "Motocultor Festival"
        pages = {MOTO: home, ticket_url: news, MOTO_NEWS: MOTO_ARTICLE}
        updated, report = apply_independently_verified_updates(
            doc(row), doc(row), DAY, limit=1, tick=0,
            fetch=lambda url: pages[url])
        self.assertEqual(report["accepted"], [row["slug"]])
        item = updated["festivals"][0]
        self.assertIn("239 €", item["price"])
        self.assertIn("82 €", item["price"])
        self.assertNotIn("228 €", item["price"])
        self.assertIn(ticket_url, item["auditSources"])
        self.assertTrue(_verified_official_update_delta(row, item))

    def test_normal_four_day_fare_in_mixed_one_day_official_teaser(self):
        # Motocultor official homepage: 4J moved from sold-out Early Bird
        # to the normal tier, while 1J stays in sale without a price HERE.
        teaser = (
            "<main><article><p>Les trois paliers d'Early Birds sont "
            "épuisés. Le Pass 4J passe au tarif normal de 239 € hors frais "
            "de location, et les Pass 1J restent en vente.</p>"
            "</article></main>")
        self.assertEqual(advertised_passes(page(teaser).relevant()),
                         {4: "239 €"})
        # Ticket cards on the same first-party home offer the actual 1J
        # amount. Keep both distinct amounts, independent of page order.
        cards = (
            "<main><ul><li>Pass 4 jours <p>Tarif normal239 €En vente"
            "</p></li><li>Pass 1 jour <p>Journée au choix82 €En "
            "vente</p></li></ul></main>")
        offers = advertised_passes(page(cards).relevant())
        offers.update(advertised_passes(page(teaser).relevant()))
        self.assertEqual(offers, {4: "239 €", 1: "82 €"})

    def test_one_day_pass_never_borrows_four_day_price_from_same_news_teaser(self):
        # Real official news teasers mention BOTH categories in one paragraph,
        # but only the 4-day pass has a stated amount. Do not invent a 1J price.
        combined = (
            "<main><article><p>Le Pass 4J est désormais disponible au tarif "
            "normal de 239 €, et les Pass 1J restent disponibles à la vente."
            "</p></article></main>")
        self.assertEqual(advertised_passes(page(combined).relevant()),
                         {4: "239 €"})
        # Price association remains strict when the 4-day offer is sold out.
        sold_out = (
            "<main><p>Les Pass 4J Early Bird à 228 € sont SOLD OUT, et "
            "les Pass 1J sont disponibles sans tarif annoncé.</p></main>")
        self.assertEqual(advertised_passes(page(sold_out).relevant()), {})

    def test_artist_alias_cannot_collapse_without_current_official_roster(self):
        from grossesondes_existing_official_updates import verified_artist_alias_cleanup
        long_billing = "John Bush celebrating the songs of Anthrax, 1993-2003"
        old = ["Helloween", "John Bush", long_billing]
        self.assertEqual(verified_artist_alias_cleanup(old, []), old)
        self.assertEqual(
            verified_artist_alias_cleanup(old, [long_billing]),
            ["Helloween", long_billing])
        self.assertEqual(
            verified_artist_alias_cleanup(
                ["Foo", "Foo Fighters"], ["Foo Fighters"]),
            ["Foo", "Foo Fighters"])

    def test_no_rogue_host_or_old_edition_proof(self):
        a = page(HOME)
        self.assertEqual(linked_pages(MOZHELL, a), [ARTICLE])
        # Production homepage has a relative "fr/news" href from /fr/;
        # never request its broken /fr/fr/news variant.
        relative_locale = page(HOME.replace('href="/fr/', 'href="fr/'))
        self.assertEqual(linked_pages(MOZHELL, relative_locale), [ARTICLE])
        row = festival("mozhell-open-air", MOZHELL)
        old = NEWS.replace("MozHell en 2027", "MozHell en 2026")
        got, report = apply_independently_verified_updates(
            doc(row), doc(row), DAY, limit=1, tick=0,
            fetch=lambda u: HOME if u == MOZHELL else old)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(got["festivals"][0], row)
        forbidden = (
            "<main><p>Festival 2027.</p>"
            "<script>groupes annoncés : Unfounded Band</script>"
            "<p style='display:none'>Groupe Z, Groupe W, Groupe U</p>"
            "</main>")
        self.assertEqual(listed_artists(page(forbidden).relevant()), [])
        self.assertEqual(advertised_passes(page(forbidden).relevant()), {})

    def test_untrusted_stale_new_site_and_unsupported_fields_never_accepted(self):
        a = festival("new", MOZHELL)
        b = deepcopy(a)
        b["lineup"] = ["Ultra Vomit"]
        b["bands"] = 1
        b["auditSources"] += [ARTICLE]
        self.assertTrue(_verified_official_update_delta(a, b))
        for key, value in (("venue", "Invented"), ("lat", 48.0),
                           ("startDate", "2027-07-01"),
                           ("showOnMap", True), ("status", "Annulé")):
            with self.subTest(field=key):
                changed = deepcopy(b)
                changed[key] = value
                self.assertFalse(_verified_official_update_delta(a, changed))
        changed = deepcopy(b)
        changed["auditSources"].append("https://untrusted.example/article")
        self.assertFalse(_verified_official_update_delta(a, changed))

    def test_signed_baseline_and_newer_published_editions_retain_guard(self):
        from grossesondes_cloud_sync import safe_target
        baseline_row = festival("festival-foudre-2027", MOZHELL,
                                lineup=["Known Band"])
        # Cloud signed-head guards require a realistic published catalogue
        # cardinality, even in isolated unit regressions.
        foundation = [{"slug": f"stable-base-{i}", "name": f"Base {i}"}
                      for i in range(90)]
        before = doc(*foundation, baseline_row)
        previous = doc(*foundation, baseline_row)
        previous["festivals"][-1]["lineup"] += ["Previously Approved"]
        previous["festivals"][-1]["bands"] = 2
        next_calendar = deepcopy(previous)
        next_calendar["festivals"][-1]["lineup"] += ["New Official Band"]
        next_calendar["festivals"][-1]["bands"] = 3
        next_calendar["festivals"][-1]["lastVerified"] = DAY
        next_calendar["festivals"][-1]["auditSources"] += [ARTICLE]
        from grossesondes_preview import require
        with self.assertRaises(Exception):
            safe_target(before, next_calendar, previous)
        self.assertTrue(safe_target(
            before, next_calendar, previous,
            verified_official_updates=frozenset({"festival-foudre-2027"})))
        # The same append-only proof is eligible for editions inserted after
        # the legacy baseline, without granting a private patch authority.
        empty = doc(*foundation)
        self.assertTrue(safe_target(
            empty, next_calendar, previous,
            verified_official_updates=frozenset({"festival-foudre-2027"})))
        altered = deepcopy(next_calendar)
        altered["festivals"][-1]["venue"] = "Unverified venue"
        with self.assertRaises(Exception):
            safe_target(before, altered, previous,
                        verified_official_updates=frozenset({"festival-foudre-2027"}))

    def test_ticket_only_signed_update_without_roster_is_safe(self):
        row = festival("festival-2027", MOZHELL)
        del row["lineup"]
        row["bands"] = None
        updated = deepcopy(row)
        updated["price"] = "Pass 3 jours : 129,90 € — billetterie officielle ouverte"
        updated["auditSources"] += [ARTICLE]
        updated["lastVerified"] = DAY
        self.assertTrue(_verified_official_update_delta(row, updated))
        altered = deepcopy(updated)
        altered["status"] = "Annulé"
        self.assertFalse(_verified_official_update_delta(row, altered))

    def test_cloud_rotation_ignores_nonpublisher_ci_runs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/grossesondes-cloud-sync.yml").read_text(
            encoding="utf-8")
        publisher = (root / "scripts/grossesondes_cloud_sync.py").read_text(
            encoding="utf-8")
        # CI-only PR runs increment github.run_number without scanning sites:
        # the publisher must instead follow deterministic daily time slots.
        self.assertNotIn("GROSSES_ONDES_OFFICIAL_UPDATE_RUN:", workflow)
        self.assertIn("today.toordinal() * 2 +", publisher)
        self.assertIn("official_update_tick=rotation_tick", publisher)
        self.assertIn("official_update_limit=official_update_scan_limit(", publisher)
        self.assertNotIn("GROSSES_ONDES_OFFICIAL_UPDATE_RUN: ${{ inputs.",
                         workflow)

    def test_browser_roots_outside_raw_batch_are_checked_in_same_cycle(self):
        signed = doc(festival("mozhell-open-air", MOZHELL),
                     festival("other-festival", "https://other-festival.example.fr/"))
        ticks = [t for t in range(2)
                 if signed_rotation(signed, DAY, limit=1, tick=t)[0][0] != MOZHELL]
        self.assertEqual(len(ticks), 1)
        tick = ticks[0]
        base = signed_rotation(signed, DAY, limit=1, tick=tick)
        rotation = signed_rotation(
            signed, DAY, limit=1, tick=tick,
            browser_sites=(MOZHELL, ARTICLE, "https://unsigned.example.fr/"))
        self.assertEqual(rotation[0], base[0])
        self.assertEqual([url for url, _ in rotation], [base[0][0], MOZHELL])
        def fetch(url):
            if url == ARTICLE:
                return NEWS
            raise OSError("HTTP unavailable")
        def browser(url):
            if url == MOZHELL:
                return HOME
            raise OSError("No isolated proof")
        out, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=fetch, limit=1, tick=tick,
            browser_fetch=browser, browser_sites=(MOZHELL, ARTICLE))
        self.assertEqual(report["checked_official_hosts"], 2)
        self.assertEqual(report["browser_roots_checked"], 1)
        self.assertEqual(report["browser_recoveries"], 1)
        self.assertEqual(out["festivals"][0]["bands"], 3)

    def test_browser_extra_budget_and_deduplication_are_bounded(self):
        signed = doc(*[festival(f"festival-{i}", f"https://watch-{i}.example.fr/")
                       for i in range(70)])
        raw = signed_rotation(signed, DAY, limit=48, tick=0)
        urls = [r["officialSite"] for r in signed["festivals"]]
        combined = signed_rotation(
            signed, DAY, limit=48, tick=0, browser_sites=tuple(urls + urls))
        self.assertEqual(combined[:48], raw)
        self.assertEqual(len(combined), 56)
        self.assertEqual(len({url for url, _ in combined}), 56)
        bounded = signed_rotation(
            signed, DAY, limit=60, tick=0, browser_sites=tuple(urls))
        self.assertEqual(len(bounded), 60)

    def test_push_catches_up_all_47_signed_hosts_without_changing_daily_rotation(self):
        from grossesondes_cloud_sync import official_update_scan_limit
        self.assertEqual(official_update_scan_limit("push"), 48)
        for event in ("schedule", "workflow_run", "workflow_dispatch", "pull_request", ""):
            self.assertEqual(official_update_scan_limit(event), 24)
        rows = [festival(f"host-{i}", f"https://signed-catchup-{i}.fr/")
                for i in range(47)]
        published = doc(*rows)
        # A push run must catch up a previously unvisited host immediately.
        all_sites = signed_rotation(
            published, DAY, limit=official_update_scan_limit("push"), tick=0)
        self.assertEqual(len(all_sites), 47)
        # Normal Paris half-day slots remain exhaustive; only the unused tail
        # slot wraps to the beginning.
        morning = signed_rotation(published, DAY, limit=24, tick=0)
        evening = signed_rotation(published, DAY, limit=24, tick=1)
        self.assertEqual(len(morning), 24)
        self.assertEqual(len(evening), 24)
        self.assertEqual(len({x[0] for x in evening}), 24)
        self.assertEqual(len(set(x[0] for x in morning) & set(x[0] for x in evening)), 1)
        self.assertEqual(set(x[0] for x in all_sites),
                         {x[0] for x in morning + evening})

    def test_push_tail_batch_wraps_to_full_signed_budget(self):
        from grossesondes_cloud_sync import official_update_scan_limit
        limit = official_update_scan_limit("push")
        self.assertEqual(limit, 48)
        # In production a 48-host catch-up scanned only one site when the
        # signed pool had 49 hosts and the Paris tick selected the final
        # partial batch. It must still check the full bounded budget.
        for count in (49, 53, 59, 95):
            with self.subTest(count=count):
                rows = [festival(
                    f"festival-{i:03d}",
                    f"https://official-wrap-{i:03d}.example.fr/")
                    for i in range(count)]
                signed = doc(*rows)
                first = signed_rotation(signed, DAY, limit=limit, tick=0)
                tail = signed_rotation(signed, DAY, limit=limit, tick=1)
                first_urls = [url for url, _ in first]
                tail_urls = [url for url, _ in tail]
                self.assertEqual(len(first_urls), limit)
                self.assertEqual(len(tail_urls), limit)
                self.assertEqual(len(set(tail_urls)), limit)
                self.assertEqual(set(first_urls + tail_urls),
                                 {r["officialSite"] for r in rows})
                self.assertTrue(all(
                    len(signed_rotation(signed, DAY, limit=24, tick=t)) <= 24
                    for t in range(4)))

    def test_twenty_four_hosts_cover_signed_festival_rotation_in_three_runs(self):
        # A realistic nationwide pool of 53 independent first-party sites
        # must be completely visited in <= 3 successful cloud passes.
        rows = [festival(str(i), f"https://signed{i}.example.fr/")
                for i in range(53)]
        signed = doc(*rows)
        seen = [url for tick in range(3)
                for url, _ in signed_rotation(signed, DAY, limit=24, tick=tick)]
        self.assertEqual(len(seen), 72)
        self.assertEqual(len(set(seen)), 53)
        for tick in range(3):
            batch = [u for u, _ in signed_rotation(signed, DAY, limit=24, tick=tick)]
            self.assertEqual(len(batch), 24)
            self.assertEqual(len(set(batch)), 24)

    def test_ordinary_tail_uses_budget_without_starvation(self):
        for count in (1, 23, 24, 25, 47, 48, 49, 53, 72, 73, 121):
            with self.subTest(count=count):
                rows = [festival(f"festival-{i:03d}",
                                 f"https://ordinary-{i:03d}.example.fr/")
                        for i in range(count)]
                published = doc(*rows)
                slots = (count + 23) // 24
                # Any consecutive complete rotation covers all signed
                # sources even when it starts at the final partial slice.
                seen = set()
                for tick in range(slots - 1, 2 * slots - 1):
                    batch = [url for url, _ in signed_rotation(
                        published, DAY, limit=24, tick=tick)]
                    self.assertEqual(len(batch), min(count, 24))
                    self.assertEqual(len(set(batch)), len(batch))
                    seen.update(batch)
                self.assertEqual(seen, {r["officialSite"] for r in rows})

    def test_fresh_official_dates_clean_only_stale_historical_notes(self):
        from grossesondes_existing_official_updates import clean_obsolete_date_notes
        site = "https://www.fertoismetalfest.com/"
        row = festival(
            "fertois-metal-fest-2027", site,
            dates=("2027-08-27", "2027-08-29"))
        row["name"] = "Fertois Metal Fest 2027"
        row["notes"] = (
            "10e anniversaire : événement officiel annoncé le vendredi 27 août 2027. "
            "La date de fin n'étant pas établie, conserver startDate/endDate vides "
            "et le statut Dates à venir. Pas de période continue inventée. "
            "| Audit carte 22/10 : site officiel chemin des Deux Rivières, "
            "point sur chemin ; aucune date de fin inventée.")
        page_html = (
            "<html><head><title>Accueil | Fertois Metal Fest</title></head>"
            "<body><main><img alt='EDITION 2027 FERTOIS METAL FEST LOGO.png'>"
            "<heading>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027"
            "</heading></main></body></html>")
        before = doc(row)
        after, report = apply_independently_verified_updates(
            before, before, DAY, fetch=lambda _: page_html, limit=1, tick=0)
        entry = after["festivals"][0]
        self.assertEqual(report["accepted"], ["fertois-metal-fest-2027"])
        self.assertNotIn("date de fin n'étant pas établie", entry["notes"])
        self.assertNotIn("Dates à venir", entry["notes"])
        self.assertNotIn("période continue inventée", entry["notes"])
        self.assertNotIn("date de fin inventée", entry["notes"])
        self.assertIn("10e anniversaire", entry["notes"])
        self.assertIn("site officiel chemin des Deux Rivières", entry["notes"])
        self.assertEqual(entry["startDate"], row["startDate"])
        self.assertEqual(entry["endDate"], row["endDate"])
        self.assertEqual(entry["notes"], clean_obsolete_date_notes(row["notes"]))
        self.assertTrue(_verified_official_update_delta(row, entry))

    def test_cleanup_never_rewrites_unrelated_verified_notes(self):
        from grossesondes_existing_official_updates import clean_obsolete_date_notes
        untouched = (
            "Billetterie officielle : Pass 4 jours à 239 € ; "
            "Pass 1 jour à 82 € (hors frais). "
            "| Site de Kerampuilh, Carhaix-Plouguer. "
            "L'édition 2027 est datée et confirmée.")
        self.assertEqual(clean_obsolete_date_notes(untouched), untouched)
        # This is especially important for actual published archives, where
        # semicolon spacing must never masquer a source-backed field change.
        obsolete = (
            "L'édition 2027 est annoncée. Date de fin inconnue. "
            "Site officiel ; tarifs bientôt publiés.")
        cleaned = clean_obsolete_date_notes(obsolete)
        self.assertNotIn("Date de fin inconnue", cleaned)
        self.assertIn("tarifs bientôt publiés", cleaned)

    def test_notes_cleanup_requires_same_official_range_and_no_forgery(self):
        from grossesondes_existing_official_updates import clean_obsolete_date_notes
        site = "https://www.fertoismetalfest.com/"
        row = festival(
            "fertois-metal-fest-2027", site,
            dates=("2027-08-27", "2027-08-29"))
        row["name"] = "Fertois Metal Fest 2027"
        row["notes"] = "La date de fin reste inconnue. Adresse officielle maintenue."
        signed = doc(row)
        no_dates = "<main><h1>Fertois Metal Fest 2027</h1></main>"
        after, report = apply_independently_verified_updates(
            signed, signed, DAY, fetch=lambda _: no_dates, limit=1, tick=0)
        self.assertEqual(after["festivals"][0], row)
        self.assertEqual(report["accepted"], [])
        forged = deepcopy(row)
        forged["notes"] = "Texte non vérifié imposé par une proposition privée"
        self.assertFalse(_verified_official_update_delta(row, forged))
        with_proof_but_no_date = deepcopy(row)
        with_proof_but_no_date["notes"] = clean_obsolete_date_notes(row["notes"])
        self.assertTrue(_verified_official_update_delta(
            row, with_proof_but_no_date))
        # The deterministic delta guard is NOT a substitute for fresh proof:
        # only apply_independently_verified_updates may add the slug.

    def test_rotation_covers_all_sites_without_closed_roster(self):
        rows = [festival(str(i), f"https://official{i}.example.fr/")
                for i in range(80)]
        signed = doc(*rows)
        got = [u for tick in range(10)
               for u, _ in signed_rotation(signed, DAY, limit=8, tick=tick)]
        self.assertEqual(len(got), len(set(got)))
        self.assertEqual(len(set(got)), 80)
        older = deepcopy(rows[0])
        older["startDate"] = "2026-11-10"
        self.assertNotIn(older["officialSite"], [
            u for u, _ in signed_rotation(doc(older), DAY, limit=8, tick=0)])
        external = deepcopy(rows[1])
        external["officialSite"] = "https://www.helloasso.com/events/whatever"
        self.assertEqual(signed_rotation(doc(external), DAY), [])




class MunicipalVenueCityTests(unittest.TestCase):
    def setUp(self):
        from grossesondes_openagenda_linked_edition import MUNICIPAL_PUBLIC_CONFIDENCE
        self.site = "https://www.example.fr/evenement/rock-fest/"
        self.venue = "https://www.example.fr/culture/salle/"
        self.row = festival("fictional-rock-fest-2026", self.site,
                            dates=("2026-11-28", "2026-11-28"))
        self.row.update(name="Fictional Rock Fest 2026", source=self.site,
                        sourceConfidence=MUNICIPAL_PUBLIC_CONFIDENCE)
        self.html = (
            "<html><head><title>Fictional Rock Fest #3 - Ville-Test, "
            "site officiel de la Mairie</title></head><body>"
            '<nav><a href="/culture/salle/">Salle des Musiques</a></nav>'
            "<main><h2>Fictional Rock Fest #3</h2>"
            "<h3>28 novembre 2026</h3>"
            "<p>Troisième édition du festival métal au Salle des Musiques.</p>"
            "</main></body></html>")
        self.venue_html = ("<main><p>12 rue des Lilas<br>12345 Ville-Test</p>"
                           "<h1>Salle des Musiques</h1><p>Concerts.</p></main>")

    def prove(self, html=None, venue=None, reproof=True, row=None):
        from grossesondes_existing_official_updates import signed_municipal_venue_city
        calls = []
        def fetch(url):
            calls.append(url)
            return {self.venue: self.venue_html if venue is None else venue}[url]
        def check(city, title, day, fetch):
            self.assertEqual(city, "Ville-Test")
            return (self.site, ("2026-11-28", "2026-11-28")) if reproof else None
        result = signed_municipal_venue_city(
            self.html if html is None else html, self.row if row is None else row,
            DAY, fetch, municipal_prover=check)
        return result, calls

    def test_named_municipal_venue_postal_city_and_fresh_origin(self):
        claim, calls = self.prove()
        self.assertEqual(claim, {"slug": self.row["slug"], "city": "Ville-Test",
                                 "source": self.site, "venue_source": self.venue,
                                 "venue_name": "Salle des Musiques"})
        self.assertEqual(calls, [self.venue])

    def test_signed_commune_gains_only_proved_venue_and_reconciles_note(self):
        from unittest.mock import patch
        from grossesondes_openagenda_linked_edition import MUNICIPAL_PUBLIC_NOTES
        row = dict(self.row, venue=None, city="Ville-Test",
                   geoPrecision="commune", showOnMap=True, lat=48.0, lon=2.0,
                   geoVerification={"proofMode": "current-edition-commune-direct-official.v1",
                                    "markerMeaning": "centre_indicatif_de_commune"},
                   notes=MUNICIPAL_PUBLIC_NOTES)
        signed = doc(row)
        with patch("grossesondes_existing_official_updates._reprove_signed_municipal_origin",
                   return_value=True):
            output, report = apply_independently_verified_updates(
                signed, signed, DAY,
                fetch=lambda u: {self.site: self.html, self.venue: self.venue_html}[u],
                limit=1, tick=0)
        updated = output["festivals"][0]
        self.assertEqual(updated["venue"], "Salle des Musiques")
        self.assertEqual(updated["lat"], row["lat"])
        self.assertEqual(updated["lon"], row["lon"])
        self.assertIn("centre de la commune", updated["notes"])
        self.assertIn(self.venue, updated["auditSources"])
        self.assertTrue(_verified_official_update_delta(row, updated))
        self.assertFalse(_verified_official_update_delta(
            dict(row, venue="Existing venue"), updated))
        self.assertFalse(_verified_official_update_delta(
            row, dict(updated, notes="Unrelated claim")))
        self.assertFalse(_verified_official_update_delta(
            row, dict(updated, auditSources=[self.site])))

    def test_cms_repeats_identical_municipal_title_suffix(self):
        repeated = self.html.replace(
            "site officiel de la Mairie</title>",
            "site officiel de la Mairie     Ville-Test, site officiel de la Mairie</title>")
        self.assertIsNotNone(self.prove(html=repeated)[0])
        self.assertIsNone(self.prove(html=repeated.replace(
            "     Ville-Test,", "     Autre-Ville,"))[0])

    def test_municipal_title_is_not_event_location(self):
        self.assertIsNone(self.prove(html=self.html.replace(
            "au Salle des Musiques", "en tournée"))[0])

    def test_wrong_venue_heading_and_postal_city_rejected(self):
        self.assertIsNone(self.prove(venue=self.venue_html.replace(
            "Salle des Musiques", "Autre Salle"))[0])
        self.assertIsNone(self.prove(venue=self.venue_html.replace(
            "12345 Ville-Test", "12345 Autre-Ville"))[0])

    def test_cross_host_and_failed_independent_attribution_rejected(self):
        self.assertIsNone(self.prove(html=self.html.replace(
            'href="/culture/salle/"', 'href="https://outside.example/salle/"'))[0])
        self.assertIsNone(self.prove(reproof=False)[0])

    def test_footer_address_and_hidden_link_are_not_location_evidence(self):
        self.assertIsNone(self.prove(venue=(
            "<main><h1>Salle des Musiques</h1><p>Concerts.</p></main>"
            "<footer>12 rue des Lilas 12345 Ville-Test</footer>"))[0])
        self.assertIsNone(self.prove(html=self.html.replace(
            '<nav><a href=', '<nav style="visibility: hidden"><a href='))[0])
        self.assertIsNone(self.prove(html=self.html.replace(
            '<nav><a href=', '<nav hidden><a href='))[0])

    def test_two_distinct_named_venues_are_not_resolved_arbitrarily(self):
        html = self.html.replace(
            "</nav>", '<a href="/culture/autre/">Autre Salle</a></nav>').replace(
            "au Salle des Musiques.", "au Salle des Musiques et a Autre Salle.")
        result, calls = self.prove(html=html)
        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_hidden_void_element_does_not_poison_following_visible_menu(self):
        html = self.html.replace("<nav>", (
            '<div hidden><input/><br/><div>hidden</div></div><nav>'))
        self.assertIsNotNone(self.prove(html=html)[0])

    def test_signed_origin_recheck_does_not_depend_on_current_agenda_index(self):
        from unittest.mock import patch
        from grossesondes_existing_official_updates import _reprove_signed_municipal_origin
        mod = "national_municipal_source_research"
        with patch(mod + ".verified_commune", return_value={
                "city": "Ville-Test", "codeInsee": "12345"}), \
             patch(mod + ".fetch_dila_records", return_value={}), \
             patch(mod + ".verified_mairie_site", return_value="https://www.example.fr/"):
            self.assertTrue(_reprove_signed_municipal_origin("Ville-Test", self.site))
            self.assertFalse(_reprove_signed_municipal_origin(
                "Ville-Test", "https://different.example.fr/event/"))

    def test_unsigned_and_cancelled_event_not_location_authority(self):
        self.assertIsNone(self.prove(row=dict(self.row, sourceConfidence="unknown"))[0])
        self.assertIsNone(self.prove(html=self.html.replace(
            "Troisième édition", "Événement annulé. Troisième édition"))[0])


if __name__ == "__main__":
    unittest.main()


class DailyProgrammeTests(unittest.TestCase):
    def test_complete_current_daily_programme_excludes_non_music_and_venue(self):
        from grossesondes_existing_official_updates import daily_programme_artists, page
        site = "https://festival-exemple.fr/"
        row = festival("festival-exemple-2027", site, dates=("2027-08-13", "2027-08-15"))
        row["name"] = "Festival Exemple 2027"
        html = ("<html><head><title>Festival Exemple | Musiques</title></head><body><main>"
                "<h2>Programme 2027</h2><h1>† vendredi 13 août †</h1>"
                "<p>EXPOSITION : Peintre | GALERIE</p>"
                "<h1>† samedi 14 août †</h1><p>CONCERTS : Alpha † New Artist | SALLE DU REX</p>"
                "<h1>† dimanche 15 août †</h1><p>CONCERTS : Third Act • Fourth Act | SALLE B</p>"
                "<p>CINEMA : Film | SALLE C</p></main></body></html>")
        expected = ["Alpha", "New Artist", "Third Act", "Fourth Act"]
        self.assertEqual(daily_programme_artists(page(html), html, row, DAY), expected)
        original = doc(row)
        new, report = apply_independently_verified_updates(
            original, original, DAY, tick=0, fetch=lambda _: html,
            commune_resolver=lambda *_: None)
        self.assertEqual(new["festivals"][0]["lineup"], expected)
        self.assertTrue(_verified_official_update_delta(row, new["festivals"][0]))
        dated_opening = html.replace("Programme 2027", "Programme").replace(
            "EXPOSITION : Peintre", "EXPOSITION : Vernissage le 13 août 2027")
        self.assertEqual(daily_programme_artists(page(dated_opening), dated_opening, row, DAY), expected)
        no_year = dated_opening.replace("13 août 2027", "13 août")
        self.assertEqual(daily_programme_artists(page(no_year), no_year, row, DAY), [])
        for altered in (
            html.replace("Programme 2027", "Programme 2026"),
            html.replace("dimanche 15", "lundi 15"),
            html.replace("dimanche 15 août", "dimanche 22 août"),
            html.replace("Festival Exemple |", "Autre Festival |"),
            html.replace("<h1>† dimanche 15 août †</h1>", ""),
            html.replace("EXPOSITION", "CONCERT ANNULÉ"),
        ):
            self.assertEqual(daily_programme_artists(page(altered), altered, row, DAY), [])


class FreshPosterPublisherTests(unittest.TestCase):
    def setUp(self):
        self.site = "https://festival-exemple.fr/"
        self.row = festival("festival-exemple-2027", self.site,
                            dates=("2027-08-13", "2027-08-15"))
        self.row["name"] = "Festival Exemple 2027"
        self.image = self.site + "exemple-2027.jpg"
        self.home = ("<main><h1>Festival Exemple 2027</h1>"
                     "<p>Festival Exemple du 13 au 15 août 2027</p>"
                     '<img src="/exemple-2027.jpg"></main>')
        self.reading = self.make_reading("Artistes : Alpha, New Artist", "Pass 3J : 75 €")

    def make_reading(self, *extra):
        words = []
        for y, line in enumerate(("FESTIVAL EXEMPLE", "13 au 15 août 2027", *extra)):
            x = 20
            for token in line.split():
                width = len(token) * 10
                words.append({"text": token, "confidence": 98,
                              "box": [x, y * 40, width, 25], "review_only": True})
                x += width + 8
        return {"status": "review_only", "review_only": True,
                "sha256": "a" * 64, "words": words}

    def run_update(self, *, html=None, rendered=None, reader=None):
        from unittest.mock import Mock
        reader = reader or Mock(return_value=self.reading)
        original = doc(self.row)
        result, report = apply_independently_verified_updates(
            original, original, DAY, tick=0, fetch=lambda _: html if html is not None else self.home,
            browser_fetch=(lambda _: rendered) if rendered else None,
            browser_sites=(self.site,) if rendered else (),
            poster_reader=reader, commune_resolver=lambda *_: None)
        return original["festivals"][0], result["festivals"][0], report, reader

    def test_fresh_current_poster_proves_additive_roster_and_announced_price(self):
        old, new, report, reader = self.run_update()
        reader.assert_called_once_with(self.site, self.image, cache={})
        self.assertEqual(new["lineup"], ["Alpha", "New Artist"])
        self.assertEqual(new["bands"], 2)
        self.assertEqual(new["price"], "Tarifs annoncés — Pass 3 jours : 75 €")
        self.assertNotIn("ouverte", new["price"])
        self.assertIn(self.image, new["auditSources"])
        self.assertTrue(_verified_official_update_delta(old, new))
        self.assertEqual(report["fresh_poster_images_read"], 1)

    def test_first_verified_lineup_initializes_unknown_legacy_fields(self):
        for legacy in (None, [], ["Existing Artist"]):
            with self.subTest(legacy=legacy):
                self.row["bands"] = None
                if legacy is None:
                    self.row.pop("lineup", None)
                else:
                    self.row["lineup"] = legacy
                old, new, report, _ = self.run_update()
                expected = (legacy or []) + ["Alpha", "New Artist"]
                self.assertEqual(new["lineup"], expected)
                self.assertEqual(new["bands"], len(expected))
                self.assertTrue(_verified_official_update_delta(old, new))
                wrong = dict(new, bands=len(expected) + 1)
                self.assertFalse(_verified_official_update_delta(old, wrong))
                if legacy:
                    self.assertFalse(_verified_official_update_delta(
                        old, dict(new, lineup=["Alpha"], bands=1)))
        self.row["lineup"] = []
        self.row["bands"] = 8
        old, new, report, _ = self.run_update()
        self.assertEqual(new["lineup"], [])
        self.assertEqual(new["bands"], 8)
        self.assertFalse(_verified_official_update_delta(
            old, dict(new, lineup=["Alpha"], bands=1)))

    def test_rendered_candidate_rechecked_and_existing_price_preserved(self):
        self.row["price"] = "Ancien tarif"
        old, new, report, reader = self.run_update(
            html="<main>Loading</main>", rendered=self.home)
        reader.assert_called_once_with(self.site, self.image, cache={})
        self.assertEqual(new["lineup"], ["Alpha", "New Artist"])
        self.assertEqual(new["price"], "Ancien tarif")
        self.assertTrue(_verified_official_update_delta(old, new))

    def test_wrong_edition_external_image_and_missing_digest_cannot_publish(self):
        from unittest.mock import Mock
        for html in (self.home.replace("13 au 15", "20 au 22"),
                     self.home.replace("/exemple-2027.jpg", "https://external.example/exemple-2027.jpg")):
            old, new, report, reader = self.run_update(html=html)
            reader.assert_not_called()
            self.assertEqual(new["lineup"], [])
            self.assertIsNone(new["price"])
        reading = dict(self.reading, sha256=None)
        old, new, report, _ = self.run_update(reader=Mock(return_value=reading))
        self.assertEqual(new["lineup"], [])
        self.assertIsNone(new["price"])

    def test_429_stops_same_host_and_never_uses_private_cache(self):
        from unittest.mock import Mock
        reader = Mock(return_value={"status": "rate_limited"})
        html = self.home.replace("</main>", '<img src="/poster-2027.jpg"></main>')
        old, new, report, _ = self.run_update(html=html, reader=reader)
        reader.assert_called_once()
        self.assertEqual(new["lineup"], [])
        self.assertIsNone(new["price"])

    def test_poster_on_official_linked_programme_page(self):
        from unittest.mock import Mock
        programme = self.site + "programmation/"
        root = self.home.replace('<img src="/exemple-2027.jpg">',
                                 '<a href="/programmation/">Programmation</a>')
        linked = self.home.replace('/exemple-2027.jpg', 'exemple-2027.jpg')
        pages = {self.site: root, programme: linked}
        reader = Mock(return_value=self.reading)
        original = doc(self.row)
        result, report = apply_independently_verified_updates(
            original, original, DAY, tick=0, fetch=pages.__getitem__,
            poster_reader=reader, commune_resolver=lambda *_: None)
        reader.assert_called_once_with(self.site, programme + "exemple-2027.jpg", cache={})
        new = result["festivals"][0]
        self.assertEqual(new["lineup"], ["Alpha", "New Artist"])
        self.assertEqual(new["price"], "Tarifs annoncés — Pass 3 jours : 75 €")
        self.assertTrue(_verified_official_update_delta(original["festivals"][0], new))
        self.assertEqual(report["fresh_poster_images_read"], 1)

    def test_unlinked_or_wrong_edition_poster_page_cannot_publish(self):
        from unittest.mock import Mock
        from grossesondes_existing_official_updates import independently_read_posters
        programme = self.site + "programmation/"
        root = self.home.replace('<img src="/exemple-2027.jpg">', '')
        linked_root = root.replace("</main>",
                                   '<a href="/programmation/">Programmation</a></main>')
        for home, url, html in (
            (root, programme, self.home),
            (linked_root, "https://other.fr/programmation/", self.home),
            (linked_root, programme, self.home.replace("13 au 15", "20 au 22")),
        ):
            reader = Mock(return_value=self.reading)
            self.assertEqual(independently_read_posters(
                self.site, self.row, home, None, reader, [2],
                linked_html=[(url, html)]), ([], None, []))
            reader.assert_not_called()

    def test_429_after_valid_poster_discards_partial_proof(self):
        from unittest.mock import Mock
        from grossesondes_existing_official_updates import independently_read_posters
        from dns_pinned_https import OfficialHTTPStatusError
        html = self.home.replace("</main>", '<img src="/poster-2027.jpg"></main>')
        for limited in ({"status": "rate_limited"}, OfficialHTTPStatusError(429)):
            reader = Mock(side_effect=[self.reading, limited])
            blocked = set()
            self.assertEqual(independently_read_posters(
                self.site, self.row, html, None, reader, [2],
                rate_limited_hosts=blocked), ([], None, []))
            self.assertEqual(blocked, {self.site})
            reader.reset_mock()
            self.assertEqual(independently_read_posters(
                self.site, self.row, self.home, None, reader, [2],
                rate_limited_hosts=blocked), ([], None, []))
            reader.assert_not_called()

    def test_rate_limited_root_not_recovered_through_browser(self):
        from unittest.mock import Mock
        from dns_pinned_https import OfficialHTTPStatusError
        original = doc(self.row)
        fetch = Mock(side_effect=OfficialHTTPStatusError(429))
        browser = Mock(return_value=self.home)
        reader = Mock(return_value=self.reading)
        result, report = apply_independently_verified_updates(
            original, original, DAY, tick=0, fetch=fetch, browser_fetch=browser,
            poster_reader=reader, commune_resolver=lambda *_: None)
        fetch.assert_called_once()
        browser.assert_not_called()
        reader.assert_not_called()
        self.assertEqual(result, original)

    def test_conflicting_poster_rosters_and_prices_not_promoted(self):
        from unittest.mock import Mock
        reader = Mock(side_effect=[self.reading, self.make_reading("Artistes : Beta", "Pass 3J : 85 €")])
        html = self.home.replace("</main>", '<img src="/poster-2027.jpg"></main>')
        old, new, report, _ = self.run_update(html=html, reader=reader)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(new["lineup"], [])
        self.assertIsNone(new["price"])
