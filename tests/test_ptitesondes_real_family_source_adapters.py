"""Offline regression fixtures only: zero claimed live discoveries."""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_real_family_source_adapters import (
    MPT_AGENDA_URL, PARIS_DATA_URL, parse_montpellier_mpt_detail,
    parse_paris_explore, parse_ical, scope_proposals, coverage_report,
    classify, safe_https,
)

TODAY = date(2026, 11, 17)
MPT = "https://mpt.montpellier.fr/evenement/parcours-motricite"
PARIS = "https://www.paris.fr/evenements/atelier-dessin-jeunes-98765"

MPT_HTML = """<html><nav>Adultes</nav><h1>Parcours motricité</h1>
<p>Atelier/Stage | Parentalité</p><p>Tout-petits, Enfants</p>
<p>Tout-petits, enfants de 18 mois à 6 ans</p>
<p>Lieu : Bâtiment Fanfonne Guillierme (Rue des Avant-Monts)</p>
<ul><li>17 novembre 2026 - 10:00 > 11:00</li>
<li>18 novembre 2026 - 10:00 > 11:00</li>
<li>20 janvier 2027 - 10:00 > 11:00</li></ul>
<p>Entrée libre | Gratuit</p><p>Carte MPT obligatoire</p>
<h2>Autres événements</h2><p>29 novembre 2026 - 10:00 > 11:00</p>
</html>"""

PARIS_RECORD = {
    "id": "98765", "title": "Atelier dessin jeunes",
    "url": PARIS, "audience": "Enfants", "childrens": "oui",
    "qfap_tags": "Loisirs créatifs",
    "address_name": "Bibliothèque fictive pour test",
    "address_city": "Paris",
    "date_start": "2026-11-20T13:00:00+01:00",
    "date_end": "2026-12-20T14:00:00+01:00",
    "occurrences": "2026-11-20T13:00:00+01:00_2026-11-20T14:00:00+01:00;"
                   "2026-12-04T13:00:00+01:00_2026-12-04T14:00:00+01:00",
}
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:fictional-session-1
SUMMARY:Atelier dessin pour enfants
DESCRIPTION:Pour les enfants et les familles.
DTSTART:20261120T100000Z
DTEND:20261120T110000Z
LOCATION:Bibliothèque fictive
URL:https://mediatheque.example.org/agenda/fictional-session-1
END:VEVENT
END:VCALENDAR
"""


class OrganizerOriginTests(unittest.TestCase):
    def test_first_party_https_host_cannot_be_replaced_by_lookalike(self):
        site = "mpt.montpellier.fr"
        self.assertTrue(safe_https(
            "https://mpt.montpellier.fr/evenement/parcours-motricite",
            site, "/evenement/"))
        for bad in (
            "http://mpt.montpellier.fr/evenement/parcours-motricite",
            "https://mpt.montpellier.fr.evil.example/evenement/test",
            "https://evil.example/evenement/parcours-motricite",
            "https://user@mpt.montpellier.fr/evenement/test",
            "https://mpt.montpellier.fr:8443/evenement/test",
            "https://mpt.montpellier.fr/other/test",
            "https://mpt.montpellier.fr/evenement/test#fake",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(safe_https(bad, site, "/evenement/"))


class MptTests(unittest.TestCase):
    def test_actual_detail_structure_and_exact_sessions(self):
        rows = parse_montpellier_mpt_detail(MPT_HTML, MPT, TODAY)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["date_start"], "2026-11-18")
        self.assertEqual(rows[0]["category"], "activite-sportive")
        self.assertEqual(rows[0]["venue"], "Bâtiment Fanfonne Guillierme")
        self.assertEqual(rows[0]["city"], "Montpellier")
        self.assertEqual(rows[0]["price_evidence"], "ambiguous")
        self.assertEqual(rows[0]["registration_evidence"], "not_stated")

    def test_related_cards_must_not_contaminate_main_event(self):
        rows = parse_montpellier_mpt_detail(MPT_HTML, MPT, TODAY)
        self.assertNotIn("2026-11-29", [x["date_start"] for x in rows])

    def test_adult_only_rejected(self):
        html = MPT_HTML.replace("Tout-petits, Enfants", "Adultes").replace(
            "Tout-petits, enfants de 18 mois à 6 ans", "Adultes")
        self.assertEqual(parse_montpellier_mpt_detail(html, MPT, TODAY), [])

    def test_cancelled_rejected(self):
        html = MPT_HTML.replace("Carte MPT obligatoire", "Événement annulé")
        self.assertEqual(parse_montpellier_mpt_detail(html, MPT, TODAY), [])

    def test_no_venue_no_lead(self):
        self.assertEqual(parse_montpellier_mpt_detail(
            MPT_HTML.replace("Lieu :", "Point :"), MPT, TODAY), [])

    def test_external_host_refused(self):
        with self.assertRaises(ValueError):
            parse_montpellier_mpt_detail(
                MPT_HTML, "https://evil.example/evenement/parcours", TODAY)


class ParisTests(unittest.TestCase):
    def test_two_explicit_occurrences_not_full_range(self):
        rows = parse_paris_explore({"results": [PARIS_RECORD]}, TODAY)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date_start"], "2026-11-20")
        self.assertEqual(rows[1]["date_start"], "2026-12-04")
        self.assertEqual(rows[0]["category"], "atelier-creatif")
        self.assertEqual(rows[0]["price_evidence"], "not_stated")

    def test_range_without_occurrences_never_expands(self):
        row = {**PARIS_RECORD, "occurrences": None}
        self.assertEqual(parse_paris_explore({"results": [row]}, TODAY), [])

    def test_adult_only_and_unsafe_source_rejected(self):
        rows = [{**PARIS_RECORD, "audience": "Adultes", "childrens": "",
                 "qfap_tags": "Sports adultes"},
                {**PARIS_RECORD, "url": "https://phishing.test/agenda"}]
        self.assertEqual(parse_paris_explore({"results": rows}, TODAY), [])

    def test_timezone_midnight_crossing(self):
        row = {**PARIS_RECORD, "occurrences":
               "2026-11-20T23:30:00Z_2026-11-20T23:50:00Z"}
        rows = parse_paris_explore({"results": [row]}, TODAY)
        self.assertEqual(rows[0]["date_start"], "2026-11-21")
        self.assertEqual(rows[0]["start_local"], "00:30")

    def test_no_implicit_timezone(self):
        row = {**PARIS_RECORD, "occurrences":
               "2026-11-20T13:00:00_2026-11-20T14:00:00"}
        self.assertEqual(parse_paris_explore({"results": [row]}, TODAY), [])


class IcalTests(unittest.TestCase):
    def test_utc_time_paris_local_no_guessed_city(self):
        rows = parse_ical(ICS, "https://mediatheque.example.org/agenda.ics", TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_start"], "2026-11-20")
        self.assertEqual(rows[0]["start_local"], "11:00")
        self.assertIsNone(rows[0]["city"])
        self.assertEqual(scope_proposals(rows, TODAY), [])

    def test_explicit_paris_tzid_case_preserved(self):
        ical = ICS.replace("DTSTART:20261120T100000Z",
                           "DTSTART;TZID=Europe/Paris:20261120T100000")
        rows = parse_ical(ical, "https://mediatheque.example.org/a.ics", TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["start_local"], "10:00")

    def test_guadeloupe_explicit_utc_conversion(self):
        ical = ICS.replace("DTSTART:20261120T100000Z",
                           "DTSTART:20261120T010000Z")
        rows = parse_ical(ical, "https://mediatheque.example.org/a.ics",
                          TODAY, target_timezone="America/Guadeloupe")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_start"], "2026-11-19")
        self.assertEqual(rows[0]["start_local"], "21:00")

    def test_explicit_overseas_tzid_must_match_verified_feed_region(self):
        ical = ICS.replace("DTSTART:20261120T100000Z",
                           "DTSTART;TZID=America/Martinique:20261120T100000")
        link = "https://mediatheque.example.org/a.ics"
        self.assertEqual(parse_ical(ical, link, TODAY), [])
        rows = parse_ical(ical, link, TODAY,
                          target_timezone="America/Martinique")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["start_local"], "10:00")

    def test_unreviewed_feed_timezone_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_ical(ICS, "https://mediatheque.example.org/a.ics",
                       TODAY, target_timezone="Antarctica/Troll")

    def test_rrule_is_never_expanded(self):
        self.assertEqual(parse_ical(ICS.replace("END:VEVENT",
            "RRULE:FREQ=WEEKLY;COUNT=5\nEND:VEVENT"),
            "https://mediatheque.example.org/agenda.ics", TODAY), [])

    def test_cancelled_is_dropped(self):
        self.assertEqual(parse_ical(ICS.replace("END:VEVENT",
            "STATUS:CANCELLED\nEND:VEVENT"),
            "https://mediatheque.example.org/agenda.ics", TODAY), [])

    def test_all_day_is_not_a_timed_session(self):
        self.assertEqual(parse_ical(ICS.replace(
            "DTSTART:20261120T100000Z", "DTSTART;VALUE=DATE:20261120"),
            "https://mediatheque.example.org/agenda.ics", TODAY), [])


class MusicalIsolationTests(unittest.TestCase):
    def test_musical_conte_is_not_misrouted_as_family_lecture(self):
        self.assertIsNone(classify("Conte musical pour les enfants"))
        self.assertIsNone(classify("Concert jeunesse de musique et percussions"))

    def test_nonmusical_story_is_still_classified(self):
        self.assertEqual(classify("Heure du conte pour les enfants"),
                         "lecture-jeunesse")


class IsolationTests(unittest.TestCase):
    def test_scope_contract_and_no_approval(self):
        mpt = parse_montpellier_mpt_detail(MPT_HTML, MPT, TODAY)
        paris = parse_paris_explore({"results": [PARIS_RECORD]}, TODAY)
        checks = scope_proposals(mpt + paris, TODAY)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["structurally_plausible_for_independent_review"], 5)
        report = coverage_report({"montpellier_mpt": mpt,
                                  "paris_opendatasoft": paris}, TODAY)
        self.assertEqual(report["discovered_occurrences"], 5)
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["private_approvals"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["approval_granted_to_publisher"])

    def test_no_live_claim_from_fixtures(self):
        report = coverage_report({"ical": []}, TODAY)
        self.assertEqual(report["discovered_occurrences"], 0)
        self.assertEqual(report["published_fiches"], 0)


if __name__ == "__main__":
    unittest.main()
