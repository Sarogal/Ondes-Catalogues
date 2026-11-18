"""Adversarial first-party structured session fixtures, never real secrets."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2
from ptitesondes_openagenda_v2_structured_organizer import (
    check_structured_organizer_session,
)
from test_ptitesondes_openagenda_v2_organizer_bridge import (
    LEAD, EVENT, AGENDA, VENUE, ORGANIZER,
)

VISIBLE = ("<main><h1>Lecture pour enfants</h1>"
           "<p>Bibliothèque fictive — Villeurbanne.</p>"
           "<p>Pour les enfants et familles.</p></main>")
SESSION = {
    "@context": "https://schema.org", "@type": "Event",
    "name": "Lecture pour enfants",
    "startDate": "2026-12-05T14:30:00+01:00",
    "eventStatus": "https://schema.org/EventScheduled",
    "location": {
        "@type": "Place", "name": "Bibliothèque fictive",
        "address": {
            "@type": "PostalAddress", "addressLocality": "Villeurbanne",
        },
    },
}


def html(nodes=None, *, visible=VISIBLE):
    payload = SESSION if nodes is None else nodes
    return ("<html><body>" + visible +
            "<script type='application/ld+json'>" +
            json.dumps(payload) + "</script></body></html>")


def verify(*, lead=None, event=None, organizer=None, page_html=None,
           page_url=None, proof=None):
    l = deepcopy(lead if lead is not None else LEAD)
    e = deepcopy(event if event is not None else EVENT)
    d = proof if proof is not None else review_direct_v2(
        l, e, AGENDA, VENUE, date(2026, 11, 18))
    o = deepcopy(organizer if organizer is not None else ORGANIZER)
    p = {"url": page_url if page_url is not None else o["exact_url"],
         "html": html() if page_html is None else page_html}
    return check_structured_organizer_session(l, e, d, o, p)


class StructuredOrganizerContract(unittest.TestCase):
    def test_single_session_exact_jsonld_but_no_visible_time_is_diagnostic_only(self):
        result = verify()
        self.assertTrue(result["official_structured_sessions_concordant"], result["reason"])
        self.assertEqual(result["confirmed_local_start_times_count"], 1)
        self.assertFalse(result["organizer_ownership_attested"])
        self.assertFalse(result["age_access_fully_verified"])
        self.assertFalse(result["rights_reviewed"])
        self.assertFalse(result["publisher_connected"])
        self.assertFalse(result["approval_granted"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)

    def test_all_multiple_same_day_clocks_must_be_confirmed_independently(self):
        e = deepcopy(EVENT)
        e["timings"].append({
            "begin": "2026-12-05T16:00:00+0100",
            "end": "2026-12-05T16:45:00+0100",
        })
        denied = verify(event=e)
        self.assertFalse(denied["official_structured_sessions_concordant"])
        second = deepcopy(SESSION)
        second["startDate"] = "2026-12-05T16:00:00+01:00"
        yes = verify(event=e, page_html=html({"@graph": [SESSION, second]}))
        self.assertTrue(yes["official_structured_sessions_concordant"], yes["reason"])
        self.assertEqual(yes["confirmed_local_start_times_count"], 2)

    def test_unequal_date_timezone_and_naive_timestamp_held(self):
        for raw in (
            "2026-12-06T14:30:00+01:00",
            "2026-12-05T14:30:00",
            "2026-12-05T13:30:00+01:00",
            "2026-12-05T14:30:00Z",
            "not-a-time",
        ):
            with self.subTest(start=raw):
                p = dict(SESSION, startDate=raw)
                self.assertFalse(verify(page_html=html(p))[
                    "official_structured_sessions_concordant"])

    def test_exact_timezone_conversion_accepts_equivalent_utc_instant(self):
        # API timezone is Europe/Paris; UTC 13:30 corresponds to 14:30.
        p = dict(SESSION, startDate="2026-12-05T13:30:00Z")
        result = verify(page_html=html(p))
        self.assertTrue(result["official_structured_sessions_concordant"], result["reason"])

    def test_mismatching_name_city_venue_or_wrong_location_structure_held(self):
        for bad in (
            dict(SESSION, name="Une autre séance"),
            dict(SESSION, location={"name": "Autre bibliothèque",
                                    "address": {"addressLocality": "Villeurbanne"}}),
            dict(SESSION, location={"name": "Bibliothèque fictive",
                                    "address": {"addressLocality": "Rouen"}}),
            dict(SESSION, location="Bibliothèque fictive"),
            dict(SESSION, location=None),
            dict(SESSION, **{"@type": "CreativeWork"}),
        ):
            with self.subTest(bad=bad):
                self.assertFalse(verify(page_html=html(bad))[
                    "official_structured_sessions_concordant"])

    def test_cancelled_or_postponed_structured_event_blocked(self):
        for event_status in ("https://schema.org/EventCancelled",
                             "https://schema.org/EventPostponed",
                             "EventMovedOnline", 42):
            with self.subTest(event_status=event_status):
                r = verify(page_html=html(dict(SESSION, eventStatus=event_status)))
                self.assertFalse(r["official_structured_sessions_concordant"])

    def test_visible_page_must_confirm_title_venue_city_and_family(self):
        for section in (
            VISIBLE.replace("Lecture pour enfants", "Spectacle adulte"),
            VISIBLE.replace("Bibliothèque fictive", "Autre centre"),
            VISIBLE.replace("Villeurbanne", "Rouen"),
            VISIBLE.replace("Pour les enfants et familles.", "Atelier adultes seulement."),
        ):
            with self.subTest(section=section):
                self.assertFalse(verify(page_html=html(visible=section))[
                    "official_structured_sessions_concordant"])

    def test_neutral_title_cannot_substitute_for_absent_visible_family_audience(self):
        lead = deepcopy(LEAD)
        event = deepcopy(EVENT)
        lead["title"] = "Lecture du samedi"
        event["title"]["fr"] = "Lecture du samedi"
        node = dict(SESSION, name="Lecture du samedi")
        visible = (VISIBLE.replace("Lecture pour enfants", "Lecture du samedi")
                   .replace("Pour les enfants et familles.", "Grand public."))
        result = verify(
            lead=lead, event=event, page_html=html(node, visible=visible))
        self.assertEqual(result["reason"], "organizer_family_audience_not_visible")
        self.assertFalse(result["approval_granted"])

    def test_visible_explicit_adult_only_cancelled_and_full_are_blocking(self):
        for line in ("Réservé aux adultes uniquement",
                     "Séance annulée", "Séance reportée", "Complet"):
            r = verify(page_html=html(visible=VISIBLE + "<p>" + line + "</p>"))
            self.assertFalse(r["official_structured_sessions_concordant"])

    def test_structured_adult_cancelled_and_online_conflicts_remain_blocked(self):
        for patch in (
            {"description": "Réservé aux adultes uniquement"},
            {"description": "Événement annulé"},
            {"eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode"},
            {"eventAttendanceMode": 3},
        ):
            with self.subTest(patch=patch):
                r = verify(page_html=html(dict(SESSION, **patch)))
                self.assertFalse(r["official_structured_sessions_concordant"])
                self.assertFalse(r["approval_granted"])
        yes = verify(page_html=html(dict(
            SESSION,
            eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode",
        )))
        self.assertTrue(yes["official_structured_sessions_concordant"])

    def test_organizer_host_must_be_separately_pinned_to_same_exact_url(self):
        for bad in (
            dict(ORGANIZER, approved_host="openagenda.com",
                 exact_url="https://openagenda.com/fr/foo"),
            dict(ORGANIZER, approved_host="api.openagenda.com",
                 exact_url="https://api.openagenda.com/foo"),
            dict(ORGANIZER, approved_host="www.bibliotheque-test.fr.evil.net"),
            dict(ORGANIZER, approved_host="127.0.0.1",
                 exact_url="https://127.0.0.1/lieu"),
            dict(ORGANIZER, exact_url="http://www.bibliotheque-test.fr/a"),
            dict(ORGANIZER, exact_url="https://www.bibliotheque-test.fr/a#x"),
            dict(ORGANIZER, approved_host="localhost",
                 exact_url="https://localhost/lieu"),
        ):
            with self.subTest(org=bad):
                self.assertFalse(verify(organizer=bad)[
                    "official_structured_sessions_concordant"])
        r = verify(page_url="https://www.bibliotheque-test.fr/other")
        self.assertFalse(r["official_structured_sessions_concordant"])

    def test_malformed_jsonld_missing_scripts_or_nested_false_not_accepted(self):
        for data in (
            "<h1>Lecture pour enfants</h1>",
            VISIBLE + "<script type='application/ld+json'>{broken}</script>",
            html({"@graph": [{"@type": "Organization", "name": "Bibliothèque fictive"}]}),
            html(dict(SESSION, startDate=[])),
        ):
            self.assertFalse(verify(page_html=data)[
                "official_structured_sessions_concordant"])

    def test_multiday_uid_with_scheduled_multiple_days_remains_held(self):
        e = deepcopy(EVENT)
        e["timings"].append({
            "begin": "2026-12-06T14:30:00+0100",
            "end": "2026-12-06T15:30:00+0100",
        })
        yes_day_one = verify(event=e)
        self.assertEqual(yes_day_one["reason"], "unverified_direct_single_day_proof")
        self.assertFalse(yes_day_one["approval_granted"])

    def test_source_proof_never_trusted_from_caller_boolean(self):
        forged = {
            "source_evidence_structurally_valid": True,
            "approval_granted": False, "public_writes": 0,
            "event_kind": "single_explicit_dated_occurrence",
            "explicit_local_times_for_candidate_day": ["14:30"],
        }
        self.assertFalse(verify(proof=forged)[
            "official_structured_sessions_concordant"])

    def test_all_outputs_are_fixed_counts_without_private_page_or_uid(self):
        result = verify()
        raw = json.dumps(result)
        for item in ("12345678", "bibliotheque-test.fr", "Villeurbanne",
                     "Lecture pour enfants", "oa_pk_", "14:30"):
            self.assertNotIn(item, raw)
        self.assertEqual(result["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
