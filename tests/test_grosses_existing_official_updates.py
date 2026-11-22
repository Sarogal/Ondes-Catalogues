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
        # Normal Paris half-day slots remain complementary and exhaustive.
        morning = signed_rotation(published, DAY, limit=24, tick=0)
        evening = signed_rotation(published, DAY, limit=24, tick=1)
        self.assertEqual(len(morning), 24)
        self.assertEqual(len(evening), 23)
        self.assertFalse(set(x[0] for x in morning) & set(x[0] for x in evening))
        self.assertEqual(set(x[0] for x in all_sites),
                         {x[0] for x in morning + evening})

    def test_twenty_four_hosts_cover_signed_festival_rotation_in_three_runs(self):
        # A realistic nationwide pool of 53 independent first-party sites
        # must be completely visited in <= 3 successful cloud passes.
        rows = [festival(str(i), f"https://signed{i}.example.fr/")
                for i in range(53)]
        signed = doc(*rows)
        seen = [url for tick in range(3)
                for url, _ in signed_rotation(signed, DAY, limit=24, tick=tick)]
        self.assertEqual(len(seen), 53)
        self.assertEqual(len(set(seen)), 53)
        self.assertLessEqual(len(signed_rotation(signed, DAY, limit=24, tick=0)), 24)

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


if __name__ == "__main__":
    unittest.main()
