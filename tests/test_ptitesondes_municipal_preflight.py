"""Adversarial tests for independent municipal preflight (network-free)."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_municipal_preflight import (
    SCHEMA, audit_municipal, official_calendar_verified,
    official_event_verified, municipal_calendar_url, local_time_present,
    CalendarCards, calendar_card_date_matches,
)
from test_ptitesondes_nonmusic_release_contract import (
    TODAY, URL, TITLE, proposal, access, private_review,
    private_access, public_catalogue,
)

DAY_URL = municipal_calendar_url(date(2026, 11, 25))
EVENT = f"""<html><body>
<h1>{TITLE}</h1>
<section>Médiathèque Raoul Georges Nicolo
mercredi 25 novembre de 9h à 9h30
Enfants jusqu'à 3 ans. 
</section><p>Calendrier</p>
</body></html>"""
CALENDAR = f"""<div class="media-eve">
<span class="jour">25</span><span class="mois">nov</span>
<span class="annee">2026</span>
<h2 class="eve-heading evenement-titre-3067"><a href="{URL}">{TITLE}</a></h2>
<span class="evenement-lieu-3067">Médiathèque Raoul Georges Nicolo</span>
<span class="horraires">mer. 25 nov. 09h00 - 09h30</span>
</div>"""


def candidate():
    c = proposal()
    c["calendar_url"] = DAY_URL
    return c


def check(event=EVENT, calendar=CALENDAR, c=None, a=None, other=None):
    items = {URL: event, DAY_URL: calendar}
    if other:
        items.update(other)

    def get(url):
        if url not in items:
            raise ValueError("untrusted_url")
        return items[url]
    return audit_municipal(private_review(c or candidate()),
                           private_access(a or access()),
                           public_catalogue(), TODAY, get)


class MunicipalPreflightTests(unittest.TestCase):
    def test_realistic_example_proves_page_and_calendar_but_never_authorizes(self):
        result = check()
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["examined"], 1)
        self.assertEqual(result["approved"], 0)
        self.assertEqual(result["publication_ready"], 0)
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)
        reasons = result["details_private_only"][0]["reasons"]
        self.assertIn("editorial_conditions_required", reasons)
        self.assertNotIn("calendar_occurrence_not_reconfirmed", reasons)
        self.assertNotIn("official_event_not_reconfirmed", reasons)

    def test_local_guadeloupe_clocks_exact(self):
        for hour in ("09h00", "9h00", "09h", "9h"):
            with self.subTest(hour=hour):
                self.assertTrue(local_time_present(hour, "09:00"))
        self.assertFalse(local_time_present("10h00", "09:00"))
        self.assertFalse(local_time_present("09h40", "09:30"))

    def test_official_title_age_day_hours_required(self):
        bad = [
            EVENT.replace(TITLE, "Autre titre"),
            EVENT.replace("mercredi 25 novembre", "mercredi 18 novembre"),
            EVENT.replace("9h30", "10h30"),
            EVENT.replace("Enfants jusqu'à 3 ans", "Public adultes"),
            EVENT.replace("Médiathèque Raoul Georges Nicolo", "Autre salle"),
            EVENT.replace("</section>", " Activité annulée </section>"),
            EVENT.replace("<p>Calendrier</p>", ""),
        ]
        for html in bad:
            with self.subTest(html=html[:50]):
                result = check(event=html)
                self.assertIn("official_event_not_reconfirmed",
                              result["details_private_only"][0]["reasons"])

    def test_event_hours_must_belong_to_same_date_clause(self):
        bad = EVENT.replace(
            "mercredi 25 novembre de 9h à 9h30",
            "mercredi 25 novembre. Autres créneaux : 9h puis 9h30")
        self.assertFalse(official_event_verified(candidate(), bad))
        self.assertIn("official_event_not_reconfirmed",
                      check(event=bad)["details_private_only"][0]["reasons"])

    def test_weekly_same_title_different_day_is_not_ambiguity(self):
        another_week = CALENDAR.replace("25</span>", "18</span>").replace(
            "mer. 25 nov.", "mer. 18 nov.")
        joined = CALENDAR + another_week
        self.assertTrue(official_calendar_verified(candidate(), joined))
        p = CalendarCards()
        p.feed(joined)
        self.assertEqual(len(p.cards), 2)
        self.assertEqual(
            sum(calendar_card_date_matches(row, date(2026, 11, 25))
                for row in p.cards), 1)

    def test_duplicate_sidebar_card_only_if_same_evidence(self):
        # Real public site repeats identical metadata with slightly
        # different text; it must not count as another event.
        second = CALENDAR.replace("</div>", "<p>En savoir plus</p></div>")
        self.assertTrue(official_calendar_verified(candidate(), CALENDAR + second))
        self.assertFalse(official_calendar_verified(
            candidate(), CALENDAR + second.replace("09h30", "10h30")))
        self.assertFalse(official_calendar_verified(
            candidate(), CALENDAR + second.replace(URL, URL + "-other")))
        self.assertFalse(official_calendar_verified(
            candidate(), CALENDAR + second.replace(
                "Médiathèque Raoul Georges Nicolo",
                "Autre bibliothèque")))
        self.assertFalse(official_calendar_verified(
            candidate(), CALENDAR + second.replace(
                "</div>", "<p>Activité annulée</p></div>")))

    def test_day_month_year_must_be_scoped_metadata_not_prose(self):
        # Dates buried in generic text must not fill a missing official field.
        for change in (
            CALENDAR.replace('<span class="jour">25</span>',
                             '<span>25</span>'),
            CALENDAR.replace('<span class="mois">nov</span>',
                             '<span>nov</span>'),
            CALENDAR.replace('<span class="annee">2026</span>',
                             '<span>2026</span>'),
            CALENDAR.replace('<span class="annee">2026</span>',
                             '<span class="annee">2027</span>'),
        ):
            with self.subTest(change=change[:80]):
                self.assertFalse(official_calendar_verified(candidate(), change))

    def test_calendar_exact_official_event_link_required(self):
        wrong = CALENDAR.replace(URL, "https://www.villedugosier.fr/evenement/autre-3068")
        self.assertFalse(official_calendar_verified(candidate(), wrong))
        self.assertFalse(official_calendar_verified(
            candidate(), CALENDAR.replace('<a href="' + URL + '">', "<a>")))

    def test_calendar_exact_time_pair_cannot_be_scattered(self):
        broken = CALENDAR.replace("09h00 - 09h30", "09h00 puis 09h30")
        self.assertFalse(official_calendar_verified(candidate(), broken))
        self.assertIn("calendar_occurrence_not_reconfirmed",
                      check(calendar=broken)["details_private_only"][0]["reasons"])

    def test_municipal_calendar_must_be_same_card_same_id_year_hour(self):
        bad = [
            CALENDAR.replace("evenement-titre-3067", "evenement-titre-3068"),
            CALENDAR.replace("evenement-lieu-3067", "evenement-lieu-3068"),
            CALENDAR.replace("<span class=\"annee\">2026</span>",
                             "<span class=\"annee\">2027</span>"),
            CALENDAR.replace("09h30", "10h30"),
            CALENDAR.replace("Médiathèque Raoul Georges Nicolo", "Autre lieu"),
            CALENDAR.replace(TITLE, "Autre séance"),
        ]
        for html in bad:
            with self.subTest(html=html[:70]):
                result = check(calendar=html)
                self.assertIn("calendar_occurrence_not_reconfirmed",
                              result["details_private_only"][0]["reasons"])

    def test_calendar_url_must_be_exact_guadeloupe_date(self):
        c = candidate()
        c["calendar_url"] = "https://evil.example/spip.php?date_event=2026-11-25"
        result = check(c=c)
        self.assertIn("wrong_municipal_calendar",
                      result["details_private_only"][0]["reasons"])

    def test_missing_registration_and_price_are_not_assumed(self):
        reasons = check()["details_private_only"][0]["reasons"]
        self.assertIn("editorial_conditions_required", reasons)
        result = check(event=EVENT.replace("</section>", " Gratuit </section>"))
        self.assertIn("price_changed", result["details_private_only"][0]["reasons"])
        result = check(event=EVENT.replace("</section>", " Sur inscription </section>"))
        self.assertIn("registration_changed", result["details_private_only"][0]["reasons"])

    def test_conflicting_official_conditions_are_not_waived(self):
        price_html = EVENT.replace("</section>", " Gratuit. Tarif : 10 euros </section>")
        r = check(event=price_html)
        self.assertIn("conflicting_price_on_official_page",
                      r["details_private_only"][0]["reasons"])
        reg_html = EVENT.replace("</section>", " Sur inscription et sans inscription </section>")
        r = check(event=reg_html)
        self.assertIn("conflicting_registration_on_official_page",
                      r["details_private_only"][0]["reasons"])

    def test_absent_official_year_cannot_borrow_neighbor_card(self):
        no_year = CALENDAR.replace('<span class="annee">2026</span>', '')
        other = ('<div class="media-eve"><h2 class="evenement-titre-9000">'
                 'Autre activité</h2><span class="evenement-lieu-9000">'
                 'Médiathèque Raoul Georges Nicolo</span>'
                 '25 nov 2026 09h30</div>')
        self.assertFalse(official_calendar_verified(candidate(), no_year + other))

    def test_forged_price_claim_and_unsourced_registration_rejected(self):
        a = access()
        a["price_evidence"] = "explicit_free"
        self.assertIn("unverified_free", check(a=a)["details_private_only"][0]["reasons"])
        a = access()
        a["registration_evidence"] = "explicit_required"
        self.assertIn("registration_changed", check(a=a)["details_private_only"][0]["reasons"])

    def test_no_network_and_no_publication_on_fetch_failure(self):
        def fail(url):
            raise OSError("no network")
        r = audit_municipal(private_review(candidate()),
                            private_access(access()), public_catalogue(), TODAY, fail)
        self.assertEqual(r["publication_ready"], 0)
        self.assertEqual(r["public_writes"], 0)
        self.assertIn("municipal_source_unavailable", r["details_private_only"][0]["reasons"])

    def test_calendar_reuse_other_card_cannot_inject_hour(self):
        another = ("""<div class="media-eve">
<h2 class="evenement-titre-9999">Autre</h2>
<span class="evenement-lieu-9999">Médiathèque Raoul Georges Nicolo</span>
<span>25 nov 2026 09h30</span></div>""")
        malicious = CALENDAR.replace("09h30", "10h30") + another
        self.assertFalse(official_calendar_verified(candidate(), malicious))

    def test_unchanged_musical_catalogue_and_no_public_write_contract(self):
        self.assertTrue(official_event_verified(candidate(), EVENT))
        self.assertTrue(official_calendar_verified(candidate(), CALENDAR))
        report = check()
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["approved"], 0)
        self.assertNotIn("patch", report)


if __name__ == "__main__":
    unittest.main()
