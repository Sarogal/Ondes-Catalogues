"""Offline checks: promote exact future dates from one signed official homepage."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_existing_official_updates import (
    apply_independently_verified_updates, signed_rotation,
    undated_official_evidence_diagnostic, reconcile_official_date_ranges,
)
from grossesondes_cloud_sync import _verified_official_update_delta, safe_target

DAY = "2026-11-22"
SITE = "https://www.sylakopenair.com/"


def festival():
    return {"slug": "sylak-open-air-2027", "name": "Sylak Open Air 2027",
            "officialSite": SITE, "startDate": None, "endDate": None,
            "status": "Dates à venir", "verificationStatus": "Dates à confirmer",
            "lineup": [], "bands": 0, "days": None, "lastVerified": "2026-11-18",
            "auditSources": [SITE], "showOnMap": False, "lat": None, "lon": None}


def signed(*rows):
    return {"schema": 1, "generatedAt": DAY,
            "festivals": [deepcopy(x) for x in rows]}


GOOD_HTML = ("<main><h1>Sylak Open Air 2027</h1>"
             "<p>Sylak Open Air 2027 : 30 au 31 juillet 2027.</p></main>")


class UndatedOfficialDateTests(unittest.TestCase):
    def updated(self, html, row=None):
        row = row or festival()
        original = signed(row)
        result, report = apply_independently_verified_updates(
            original, original, DAY, limit=1, tick=0, fetch=lambda url: html)
        return result["festivals"][0], report

    def test_diagnostics_distinguish_raw_visible_identity_without_html_leak(self):
        old = festival()
        html = (
            "<html><head><title>Accueil | Sylak Open Air</title></head>"
            "<body><main><img alt='Edition 2027 Sylak Open Air logo'>"
            "<h2>VENDREDI 30 SAMEDI 31 JUILLET 2027</h2>"
            "</main></body></html>")
        flags = undated_official_evidence_diagnostic(html, old, 2027)
        self.assertEqual(flags, {
            "raw_year_token": True,
            "visible_year_token": True,
            "visible_weekday_sequence": True,
            "title_matches_identity": True,
            "current_edition_logo_alt": True,
        })
        published, report = self.updated(html, old)
        self.assertEqual(published["startDate"], "2027-07-30")
        evidence = report["official_edition_diagnostics"][0]["undated_page_proof"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["page_role"], "registered_home")
        self.assertTrue(evidence[0]["weekday_date_validator"])
        self.assertNotIn("Sylak Open Air", str(evidence))
        self.assertNotIn("VENDREDI", str(evidence))

    def test_undated_proof_flags_do_not_authorize_publication(self):
        old = festival()
        html = ("<html><body><script>Sylak Open Air 2027:"
                "VENDREDI 30 SAMEDI 31 JUILLET 2027</script>"
                "</body></html>")
        flags = undated_official_evidence_diagnostic(html, old, 2027)
        self.assertTrue(flags["raw_year_token"])
        self.assertFalse(flags["visible_year_token"])
        self.assertFalse(flags["visible_weekday_sequence"])
        new, report = self.updated(html, old)
        self.assertEqual(new, old)
        self.assertEqual(report["accepted"], [])

    def test_full_official_weekend_and_contained_single_day_agree(self):
        from datetime import date
        from unittest.mock import patch
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        homepage = (
            "<html><head><title>Accueil | Fertois Metal Fest</title></head>"
            "<body><main>"
            "<img alt='EDITION 2027 FERTOIS METAL FEST LOGO.png'>"
            "<heading>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027"
            "</heading></main></body></html>")
        full = (date(2027, 8, 27), date(2027, 8, 29))
        last_day = (date(2027, 8, 29), date(2027, 8, 29))
        self.assertEqual(reconcile_official_date_ranges({full, last_day}),
                         full)
        before = signed(old)
        with patch("grossesondes_existing_official_updates.official_date",
                   return_value=last_day):
            after, report = apply_independently_verified_updates(
                before, before, DAY, fetch=lambda _: homepage, limit=1, tick=0)
        item = after["festivals"][0]
        self.assertEqual((item["startDate"], item["endDate"]),
                         ("2027-08-27", "2027-08-29"))
        self.assertEqual(item["days"], "3")
        self.assertEqual(report["accepted"], [old["slug"]])
        self.assertTrue(report["official_edition_diagnostics"][0][
            "undated_page_proof"][0]["date_readings_differ"])
        self.assertTrue(_verified_official_update_delta(old, item))

    def test_distinct_multi_day_intervals_remain_contradictory(self):
        from datetime import date
        from unittest.mock import patch
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        homepage = (
            "<html><title>Fertois Metal Fest</title>"
            "<img alt='EDITION 2027 FERTOIS METAL FEST LOGO'>"
            "<p>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOUT 2027</p></html>")
        conflicting = (date(2027, 8, 27), date(2027, 8, 28))
        full = (date(2027, 8, 27), date(2027, 8, 29))
        self.assertIsNone(reconcile_official_date_ranges({full, conflicting}))
        before = signed(old)
        with patch("grossesondes_existing_official_updates.official_date",
                   return_value=conflicting):
            after, report = apply_independently_verified_updates(
                before, before, DAY, fetch=lambda _: homepage, limit=1, tick=0)
        self.assertEqual(after["festivals"][0], old)
        self.assertEqual(report["accepted"], [])

    def test_future_date_exact_official_single_source_publishes(self):
        old = festival()
        self.assertEqual(signed_rotation(signed(old), DAY, 1, 0)[0][0], SITE)
        new, report = self.updated(GOOD_HTML, old)
        self.assertEqual((new["startDate"], new["endDate"]),
                         ("2027-07-30", "2027-07-31"))
        self.assertEqual(new["days"], "2")
        self.assertEqual(new["status"], "Annoncé")
        self.assertEqual(new["verificationStatus"],
                         "Dates confirmées sur le site officiel")
        self.assertTrue(_verified_official_update_delta(old, new))
        self.assertEqual(report["accepted"], [old["slug"]])
        self.assertEqual(new["auditSources"], [SITE])

    def test_publisher_requires_its_own_recheck_and_allows_no_other_change(self):
        old = festival()
        new, report = self.updated(GOOD_HTML, old)
        foundation = [{"slug": f"base-{i}", "name": f"Base {i}"}
                      for i in range(90)]
        before = signed(*foundation, old)
        after = signed(*foundation, new)
        with self.assertRaises(Exception):
            safe_target(before, after, before)
        self.assertTrue(safe_target(
            before, after, before,
            verified_official_updates=frozenset(report["accepted"])))
        for key, bad in (("venue", "Wrong location"),
                         ("startDate", "2026-07-30"),
                         ("endDate", "2027-08-15"),
                         ("status", "Annulé"),
                         ("lat", 46.0)):
            altered = deepcopy(new)
            altered[key] = bad
            with self.subTest(key=key):
                self.assertFalse(_verified_official_update_delta(old, altered))

    def test_old_edition_single_opening_day_and_conflicting_ranges_rejected(self):
        sources = (
            "<main><h1>Sylak Open Air 2026</h1><p>30 au 31 juillet 2026</p></main>",
            "<main><h1>Sylak Open Air 2027</h1><p>30 juillet 2027</p></main>",
            ("<main><p>Sylak Open Air 2027 : 30 au 31 juillet 2027</p>"
             "<p>Sylak Open Air 2027 : 15 au 16 août 2027</p></main>"),
            "<script>Sylak Open Air 2027 : 30 au 31 juillet 2027</script>",
        )
        for source in sources:
            with self.subTest(source=source[:80]):
                new, report = self.updated(source)
                self.assertEqual(report["accepted"], [])
                self.assertEqual(new, festival())

    def test_linked_first_party_news_alone_can_confirm_dates(self):
        old = festival()
        article = SITE + "actualites/dates-2027"
        home = ("<main><h1>Sylak Open Air 2027</h1>"
                '<a href="/actualites/dates-2027">Annonce dates 2027</a></main>')
        pages = {SITE: home, article: GOOD_HTML}
        signed_doc = signed(old)
        actual, report = apply_independently_verified_updates(
            signed_doc, signed_doc, DAY, limit=1, tick=0,
            fetch=lambda url: pages[url])
        new = actual["festivals"][0]
        self.assertEqual((new["startDate"], new["endDate"]),
                         ("2027-07-30", "2027-07-31"))
        self.assertEqual(new["auditSources"], [SITE, article])
        self.assertTrue(_verified_official_update_delta(old, new))
        self.assertEqual(report["accepted"], [old["slug"]])

    def test_conflicting_official_linked_dates_do_not_publish(self):
        old = festival()
        article = SITE + "actualites/dates-2027"
        home = (GOOD_HTML.replace("</main>",
                '<a href="/actualites/dates-2027">Annonce dates 2027</a></main>'))
        other = GOOD_HTML.replace("30 au 31 juillet", "23 au 24 juillet")
        original = signed(old)
        new, report = apply_independently_verified_updates(
            original, original, DAY, limit=1, tick=0,
            fetch=lambda url: {SITE:home, article:other}[url])
        self.assertEqual(new["festivals"][0], old)
        self.assertEqual(report["accepted"], [])

    def test_official_news_proof_never_follows_outside_domain(self):
        old = festival()
        home = ("<main><h1>Sylak Open Air 2027</h1>"
                '<a href="https://external.test/dates-2027">Annonce dates 2027</a></main>')
        calls = []
        def fetch(url):
            calls.append(url)
            return home
        before = signed(old)
        after, report = apply_independently_verified_updates(
            before, before, DAY, limit=1, tick=0, fetch=fetch)
        self.assertEqual(calls, [SITE])
        self.assertEqual(after["festivals"][0], old)
        self.assertEqual(report["accepted"], [])
    def test_fertois_real_official_weekdays_promote_full_2027_weekend(self):
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        official = (
            "<html><head><title>Accueil | Fertois Metal Fest</title></head>"
            "<body><main><h2>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027"
            "</h2><p>Chemin des deux rivières, La Ferté-sous-Jouarre</p>"
            "<p>Billetterie bientôt ouverte</p></main></body></html>"
        )
        row = signed(old)
        result, report = apply_independently_verified_updates(
            row, row, DAY, limit=1, tick=0, fetch=lambda url: official)
        new = result["festivals"][0]
        self.assertEqual((new["startDate"], new["endDate"]),
                         ("2027-08-27", "2027-08-29"))
        self.assertEqual(new["days"], "3")
        self.assertEqual(report["accepted"], [old["slug"]])
        self.assertEqual(new["auditSources"], [old["officialSite"]])
        self.assertTrue(_verified_official_update_delta(old, new))

    def test_official_weekdays_must_match_calendar_and_organizer_title(self):
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        good = ("<html><head><title>Fertois Metal Fest</title></head>"
                "<body><h2>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOUT 2027"
                "</h2></body></html>")
        bad_pages = (
            good.replace("VENDREDI 27", "JEUDI 27"),
            good.replace("Fertois Metal Fest</title>", "Other Festival</title>"),
            good.replace("29 AOUT 2027", "29 AOUT 2026"),
            good.replace("SAMEDI 28 ", ""),
            good.replace("DIMANCHE 29", "DIMANCHE 30"),
            good.replace("27 SAMEDI 28", "27 SAMEDI 28") +
            "<p>VENDREDI 20 SAMEDI 21 DIMANCHE 22 AOUT 2027</p>",
        )
        for html in bad_pages:
            with self.subTest(html=html[:90]):
                target = signed(old)
                actual, report = apply_independently_verified_updates(
                    target, target, DAY, limit=1, tick=0,
                    fetch=lambda url: html)
                self.assertEqual(actual["festivals"][0], old)
                self.assertEqual(report["accepted"], [])

    def test_titleless_official_wix_heading_and_current_year_logo_confirms_dates(self):
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        wix = ("<html><body><main>"
               '<img alt="EDITION 2027 FERTOIS METAL FEST LOGO" src="/logo.png">'
               "<heading>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027</heading>"
               "<p>Chemin des 2 Rivières • La Ferté-sous-Jouarre</p>"
               "</main></body></html>")
        original = signed(old)
        result, report = apply_independently_verified_updates(
            original, original, DAY, limit=1, tick=0, fetch=lambda _: wix)
        current = result["festivals"][0]
        self.assertEqual((current["startDate"], current["endDate"]),
                         ("2027-08-27", "2027-08-29"))
        self.assertEqual(current["days"], "3")
        self.assertTrue(_verified_official_update_delta(old, current))
        self.assertEqual(report["accepted"], [old["slug"]])

    def test_titleless_logo_must_be_visible_brand_and_exact_future_year(self):
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        body = ("<heading>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027</heading>")
        images = (
            '<img alt="EDITION 2026 FERTOIS METAL FEST LOGO">',
            '<img alt="EDITION 2027 ANOTHER ROCK FEST LOGO">',
            '<img style="display:none" alt="EDITION 2027 FERTOIS METAL FEST">',
            '<img hidden alt="EDITION 2027 FERTOIS METAL FEST LOGO">',
            '<img aria-hidden="true" alt="EDITION 2027 FERTOIS METAL FEST">',
        )
        for image in images:
            with self.subTest(image=image):
                official = "<html><body>" + image + body + "</body></html>"
                original = signed(old)
                result, report = apply_independently_verified_updates(
                    original, original, DAY, limit=1, tick=0,
                    fetch=lambda _: official)
                self.assertEqual(result["festivals"][0], old)
                self.assertEqual(report["accepted"], [])

    def test_official_title_with_conflicting_year_blocks_logo_fallback(self):
        old = festival()
        old.update(slug="fertois-metal-fest-2027",
                   name="Fertois Metal Fest 2027",
                   officialSite="https://www.fertoismetalfest.com/")
        old["auditSources"] = [old["officialSite"]]
        html = ("<html><head><title>Fertois Metal Fest 2026</title></head>"
                "<body><img alt=\'EDITION 2027 FERTOIS METAL FEST LOGO\'>"
                "<heading>VENDREDI 27 SAMEDI 28 DIMANCHE 29 AOÛT 2027"
                "</heading></body></html>")
        original = signed(old)
        result, report = apply_independently_verified_updates(
            original, original, DAY, limit=1, tick=0, fetch=lambda _: html)
        self.assertEqual(result["festivals"][0], old)
        self.assertEqual(report["accepted"], [])

    def test_future_rotation_rejects_previous_year_or_unpinned_identity(self):
        old = festival()
        old["name"], old["slug"] = "Sylak Open Air 2025", "sylak-open-air-2025"
        self.assertEqual(signed_rotation(signed(old), DAY, 1, 0), [])
        forged = festival()
        forged["name"] = "An unrelated series 2027"
        self.assertEqual(signed_rotation(signed(forged), DAY, 1, 0)[0][0], SITE)
        # The publisher still needs exact edition/site proof. A forged
        # year-matching name alone never authorizes mutation.
        new, report = self.updated(GOOD_HTML, forged)
        self.assertEqual(report["accepted"], [])
        self.assertEqual(new, forged)


if __name__ == "__main__":
    unittest.main()
