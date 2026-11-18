"""Adversarial offline tests for generic organizer corroboration, no writes."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2
from ptitesondes_openagenda_v2_organizer_bridge import (
    check_independent_session, dry_run_first_party_fallback,
)
from ptitesondes_openagenda_v2_preintegration import (
    agenda_identity_for_review, group_multi_day,
)

LEAD = {
    "source_url": "https://openagenda.com/commune-test/events/12345678_lecture",
    "external_id": "12345678", "title": "Lecture pour enfants",
    "city": "Villeurbanne", "venue": "Bibliothèque fictive",
    "date_start": "2026-12-05", "date_end": "2026-12-05",
}
EVENT = {
    "uid": 12345678, "state": 2, "status": 1,
    "attendanceMode": 1, "timezone": "Europe/Paris",
    "title": {"fr": "Lecture pour enfants"},
    "description": {"fr": "Séance pour les enfants et familles"},
    "rights": {"license": {"id": "etalab-2.0"},
               "licensor": {"name": "Organisme de test"}},
    "location": {"name": "Bibliothèque fictive", "adminLevel4": "Villeurbanne",
                 "countryCode": "FR", "latitude": 45.758, "longitude": 4.9},
    "timings": [{"begin": "2026-12-05T14:30:00+0100",
                 "end": "2026-12-05T15:30:00+0100"}],
}
AGENDA = {"agenda_slug": "commune-test", "agenda_uid": "919191",
          "timezone": "Europe/Paris"}
VENUE = {"city": "Villeurbanne", "aliases": ["Bibliothèque fictive"],
         "lat": 45.758, "lng": 4.9}
ORGANIZER = {
    "approved_host": "www.bibliotheque-test.fr",
    "exact_url": "https://www.bibliotheque-test.fr/programmation/lecture",
}
HTML = """
<html><body>
<h1>Lecture pour enfants</h1>
<section>Bibliothèque fictive — Villeurbanne. Pour les enfants et familles.</section>
<ul><li>5 décembre 2026 à 14:30 : animation jeunesse</li></ul>
</body></html>
"""


def check(*, lead=None, event=None, organizer=None, html=HTML, fetched_url=None,
          direct=None):
    l = deepcopy(lead if lead is not None else LEAD)
    e = deepcopy(event if event is not None else EVENT)
    p = (direct if direct is not None else
         review_direct_v2(l, e, AGENDA, VENUE, date(2026, 11, 18)))
    info = deepcopy(organizer if organizer is not None else ORGANIZER)
    fetched = {
        "url": fetched_url if fetched_url is not None else ORGANIZER["exact_url"],
        "html": html,
    }
    return check_independent_session(l, e, p, info, fetched)


class OrganizerEvidenceContract(unittest.TestCase):
    def test_official_single_session_corroboration_but_no_admission(self):
        r = check()
        self.assertTrue(r["official_session_evidence_consistent"])
        self.assertEqual(r["confirmed_local_start_times_count"], 1)
        self.assertFalse(r["organizer_ownership_attested"])
        self.assertFalse(r["rights_reviewed"])
        self.assertFalse(r["age_access_fully_verified"])
        self.assertFalse(r["approval_granted"])
        self.assertEqual(r["public_writes"], 0)
        self.assertNotIn("additions", r)

    def test_bad_oa_proof_or_multi_day_not_organizer_confirmed(self):
        bad = check(direct={"source_evidence_structurally_valid": True})
        self.assertFalse(bad["official_session_evidence_consistent"])
        multi = deepcopy(EVENT)
        multi["timings"].append({
            "begin": "2026-12-06T14:30:00+0100",
            "end": "2026-12-06T15:30:00+0100",
        })
        self.assertEqual(check(event=multi)["reason"],
                         "no_verified_direct_single_day_evidence")

    def test_mismatching_title_venue_city_and_family_cues_fail(self):
        cases = (
            HTML.replace("Lecture pour enfants", "Spectacle adulte"),
            HTML.replace("Bibliothèque fictive", "Annexe inconnue"),
            HTML.replace("Villeurbanne", "Rouen"),
            HTML.replace("Pour les enfants et familles", "Public adultes uniquement"),
        )
        for html in cases:
            with self.subTest(html=html):
                r = check(html=html)
                self.assertFalse(r["official_session_evidence_consistent"])

    def test_date_and_time_must_be_in_same_visible_session_block(self):
        for html in (
            HTML.replace("5 décembre 2026 à 14:30",
                         "5 décembre 2026</li><li>14:30"),
            HTML.replace("5 décembre 2026 à 14:30",
                         "5 décembre 2026"),
            HTML.replace("5 décembre 2026 à 14:30",
                         "5 décembre 2027 à 14:30"),
            HTML.replace("5 décembre 2026 à 14:30",
                         '5 décembre 2026 <span aria-hidden="true">à 14:30</span>'),
        ):
            with self.subTest(html=html):
                self.assertFalse(check(html=html)[
                    "official_session_evidence_consistent"])

    def test_cancellation_postponement_and_full_refused(self):
        for status in ("Annulé", "Reportée", "Complet"):
            self.assertFalse(check(html=HTML + "<p>" + status + "</p>")[
                "official_session_evidence_consistent"])

    def test_host_must_be_exact_external_first_party_and_pinned(self):
        for organizer, fetched_url in (
            (dict(ORGANIZER, approved_host="openagenda.com"), None),
            (dict(ORGANIZER, approved_host="api.openagenda.com"), None),
            (dict(ORGANIZER, approved_host="evil.openagenda.com",
                  exact_url="https://evil.openagenda.com/programmation"), None),
            (dict(ORGANIZER, approved_host="bibliotheque-test.fr"), None),
            (dict(ORGANIZER, exact_url="https://www.bibliotheque-test.fr.evil.net/"),
             None),
            (dict(ORGANIZER, exact_url="http://www.bibliotheque-test.fr/a"), None),
            (dict(ORGANIZER, exact_url="https://www.bibliotheque-test.fr/a#fragment"),
             None),
            (ORGANIZER, "https://www.bibliotheque-test.fr/other-page"),
        ):
            with self.subTest(organizer=organizer, fetched_url=fetched_url):
                self.assertFalse(check(organizer=organizer, fetched_url=fetched_url)[
                    "official_session_evidence_consistent"])

    def test_two_sessions_require_independent_exact_evidence_for_each(self):
        event = deepcopy(EVENT)
        event["timings"].append({
            "begin": "2026-12-05T16:00:00+0100",
            "end": "2026-12-05T17:00:00+0100",
        })
        self.assertFalse(check(event=event)["official_session_evidence_consistent"])
        both = HTML.replace(
            "</ul>", "<li>5 décembre 2026 à 16:00 : seconde séance</li></ul>"
        )
        r = check(event=event, html=both)
        self.assertTrue(r["official_session_evidence_consistent"])
        self.assertEqual(r["confirmed_local_start_times_count"], 2)
        self.assertFalse(r["approval_granted"])

    def test_age_range_not_automatically_claimed_from_oa(self):
        # '6 à 8 ans' is not converted to an exact official age attestation.
        event = deepcopy(EVENT)
        event["age"] = {"min": 6, "max": 8}
        self.assertTrue(check(event=event, html=HTML + "De 6 à 8 ans.")[
            "official_session_evidence_consistent"])
        self.assertFalse(check(event=event)["age_access_fully_verified"])

    def test_first_party_can_route_without_homepage_openagenda_link(self):
        """A real, independently-pinned event session replaces a missing
        agenda-homepage link only in a NON-PUBLISHING fallback diagnostic."""
        source = {
            "agenda_uid": "919191", "agenda_slug": "commune-test",
            "timezone": "Europe/Paris",
            "institution_url": "https://www.bibliotheque-test.fr/",
            "authority_reference_url": "https://www.bibliotheque-test.fr/agenda",
        }
        identity = agenda_identity_for_review(
            {"uid": 919191, "slug": "commune-test"}, source,
        )
        self.assertTrue(identity["identity_consistent"])
        evidence = review_direct_v2(
            LEAD, EVENT, AGENDA, VENUE, date(2026, 11, 18),
        )
        result = dry_run_first_party_fallback(
            "uid_absent", LEAD, EVENT, evidence, identity,
            group_multi_day(EVENT), ORGANIZER,
            {"url": ORGANIZER["exact_url"], "html": HTML},
            historic_uid_exists=False,
        )
        self.assertEqual(result["route"],
                         "direct_source_candidate_for_remaining_gates")
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)
        bad = dry_run_first_party_fallback(
            "uid_absent", LEAD, EVENT, evidence, identity,
            group_multi_day(EVENT), ORGANIZER,
            {"url": ORGANIZER["exact_url"],
             "html": HTML.replace("5 décembre 2026 à 14:30",
                                  "5 décembre 2026")},
            historic_uid_exists=False,
        )
        self.assertEqual(bad["route"], "hold")

    def test_ods_present_and_historic_match_still_block_with_organizer(self):
        identity = agenda_identity_for_review(
            {"uid": 919191, "slug": "commune-test"},
            {"agenda_uid": "919191", "agenda_slug": "commune-test",
             "timezone": "Europe/Paris",
             "institution_url": "https://www.bibliotheque-test.fr/",
             "authority_reference_url": "https://www.bibliotheque-test.fr/agenda"},
        )
        evidence = review_direct_v2(LEAD, EVENT, AGENDA, VENUE,
                                    date(2026, 11, 18))
        for ods, historic in (("uid_present", False), ("uid_absent", True),
                              ("temporary_unavailable", False),
                              ("uid_absent", None)):
            with self.subTest(ods=ods, historic=historic):
                result = dry_run_first_party_fallback(
                    ods, LEAD, EVENT, evidence, identity,
                    group_multi_day(EVENT), ORGANIZER,
                    {"url": ORGANIZER["exact_url"], "html": HTML},
                    historic_uid_exists=historic,
                )
                self.assertEqual(result["route"], "hold")
                self.assertFalse(result["approval_granted"])

    def test_html_size_and_synthetic_approval_tamper_fail(self):
        self.assertFalse(check(html="")["official_session_evidence_consistent"])
        self.assertFalse(check(html="x" * 500001)["official_session_evidence_consistent"])
        direct = review_direct_v2(LEAD, EVENT, AGENDA, VENUE, date(2026, 11, 18))
        direct["approval_granted"] = True
        self.assertFalse(check(direct=direct)["official_session_evidence_consistent"])


if __name__ == "__main__":
    unittest.main()
