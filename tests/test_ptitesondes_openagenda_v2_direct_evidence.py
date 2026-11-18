"""Adversarial offline tests for API v2 source preflight.

All fixtures are synthetic. No real children, private backlog, API credentials
or network access. A verified source record cannot publish an event.
"""
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_direct_evidence import (
    review_direct_v2, read_direct_v2, redacted_batch_report,
)

TODAY = date(2026, 11, 18)
LEAD = {
    "source_url": "https://openagenda.com/fr/commune-test/events/12345678_fete-jeunesse",
    "external_id": "12345678",
    "date_start": "2026-12-05", "date_end": "2026-12-05",
    "title": "Fête jeunesse", "city": "Villeurbanne", "venue": "Salle des familles",
}
AGENDA = {
    "agenda_slug": "commune-test", "agenda_uid": "919191",
    "timezone": "Europe/Paris",
}
VENUE = {
    "city": "Villeurbanne", "aliases": ["Salle des familles"],
    "lat": 45.7580, "lng": 4.8998,
}
EVENT = {
    "uid": 12345678, "state": 2, "status": 1, "removed": False,
    "attendanceMode": 1, "timezone": "Europe/Paris",
    "title": {"fr": "Fête jeunesse"},
    "description": {"fr": "Ateliers pour enfants et familles"},
    "rights": {"license": "CC-BY-4.0"},
    "location": {
        "name": "Salle des familles", "adminLevel4": "Villeurbanne",
        "countryCode": "FR", "latitude": 45.7580,
        "longitude": 4.8998,
    },
    "timings": [{
        "begin": "2026-12-05T14:30:00+0100",
        "end": "2026-12-05T16:00:00+0100",
    }],
}


_DEFAULT = object()


def review(*, lead=_DEFAULT, event=_DEFAULT,
           agenda=_DEFAULT, venue=_DEFAULT):
    return review_direct_v2(
        deepcopy(LEAD if lead is _DEFAULT else lead),
        deepcopy(EVENT if event is _DEFAULT else event),
        deepcopy(AGENDA if agenda is _DEFAULT else agenda),
        deepcopy(VENUE if venue is _DEFAULT else venue), TODAY
    )


class OA2DirectEvidenceTests(unittest.TestCase):
    def test_single_exact_published_session_without_publication(self):
        result = review()
        self.assertTrue(result["source_evidence_structurally_valid"])
        self.assertEqual(result["event_kind"], "single_explicit_dated_occurrence")
        self.assertEqual(result["explicit_local_times_for_candidate_day"], ["14:30"])
        self.assertEqual(result["explicit_dated_days_count"], 1)
        for field in ("organizer_independently_attested",
                      "rights_reviewed", "publisher_connected",
                      "age_and_access_fully_verified", "approval_granted"):
            self.assertIs(result[field], False)
        self.assertEqual(result["public_writes"], 0)

    def test_same_uid_many_days_not_published_as_one_card_per_day(self):
        ev = deepcopy(EVENT)
        for day in range(6, 30):
            ev["timings"].append({
                "begin": f"2026-12-{day:02d}T14:30:00+0100",
                "end": f"2026-12-{day:02d}T16:00:00+0100",
            })
        result = review(event=ev)
        self.assertTrue(result["source_evidence_structurally_valid"])
        self.assertEqual(result["explicit_dated_days_count"], 25)
        self.assertEqual(result["event_kind"],
                         "multi_day_one_uid_hold_for_grouping")
        self.assertFalse(result["approval_granted"])
        self.assertEqual(result["public_writes"], 0)

    def test_range_without_explicit_timing_refused(self):
        ev = deepcopy(EVENT)
        ev["timings"] = []
        self.assertEqual(review(event=ev)["reason"], "no_explicit_timings")
        ev["timings"] = [{
            "begin": "2026-12-05", "end": "2026-12-29",
        }]
        self.assertEqual(review(event=ev)["reason"],
                         "invalid_timing_or_timezone")

    def test_second_day_claim_is_not_first_day_schedule(self):
        lead = deepcopy(LEAD)
        lead["date_start"] = lead["date_end"] = "2026-12-06"
        self.assertEqual(review(lead=lead)["reason"],
                         "uid_has_no_exact_dated_occurrence")

    def test_wrong_uid_url_slug_agenda_title_and_city_fail(self):
        lead = deepcopy(LEAD)
        for patch in (
            {"external_id": "12345679"},
            {"source_url": "https://openagenda.com/fr/unapproved/events/12345678_fete-jeunesse"},
            {"source_url": "https://evil.test/fr/commune-test/events/12345678_fete-jeunesse"},
            {"source_url": "https://openagenda.com.evil.test/fr/commune-test/events/12345678_fete-jeunesse"},
            {"source_url": "https://openagenda.com/fr/commune-test/events/12345678_fete-jeunesse?source=hack"},
            {"source_url": "https://openagenda.com/fr/commune-test/events/12345678_fete-jeunesse#anchor"},
            {"source_url": "https://openagenda.com/fr/commune-test/events/fete-jeunesse"},
        ):
            with self.subTest(patch=patch):
                x = dict(lead, **patch)
                self.assertFalse(review(lead=x)["source_evidence_structurally_valid"])
        ev = deepcopy(EVENT)
        ev["uid"] = 12345679
        self.assertEqual(review(event=ev)["reason"], "direct_api_event_uid_mismatch")
        ev = deepcopy(EVENT)
        ev["title"]["fr"] = "Autre activité"
        self.assertEqual(review(event=ev)["reason"], "api_title_mismatch")
        lead["city"] = "Rouen"
        self.assertEqual(review(lead=lead)["reason"], "candidate_venue_identity_mismatch")

    def test_missing_identity_cannot_pass_with_empty_alias(self):
        event = deepcopy(EVENT)
        event["title"]["fr"] = ""
        lead = dict(LEAD, title="")
        self.assertEqual(review(lead=lead, event=event)["reason"],
                         "api_title_mismatch")
        event = deepcopy(EVENT)
        event["location"]["name"] = ""
        lead = dict(LEAD, venue="")
        bad_venue = dict(VENUE, aliases=[""])
        self.assertEqual(review(lead=lead, event=event, venue=bad_venue)["reason"],
                         "geography_not_independently_verified")
        event = deepcopy(EVENT)
        lead = dict(LEAD, city="")
        self.assertEqual(review(lead=lead, event=event)["reason"],
                         "candidate_venue_identity_mismatch")

    def test_explicit_unpublished_cancelled_full_online_removed_block(self):
        for patch in (
            {"state": 1}, {"state": 0}, {"status": 2},
            {"status": 4}, {"status": 5}, {"status": 6},
            {"attendanceMode": 2}, {"removed": True},
        ):
            with self.subTest(patch=patch):
                self.assertFalse(review(event=dict(EVENT, **patch))[
                    "source_evidence_structurally_valid"])

    def test_geography_requires_independent_venue_within_65m(self):
        ev = deepcopy(EVENT)
        ev["location"]["latitude"] += 0.007
        self.assertEqual(review(event=ev)["reason"],
                         "geography_not_independently_verified")
        ev = deepcopy(EVENT)
        ev["location"]["name"] = "Salle des familles annexe"
        self.assertEqual(review(event=ev)["reason"],
                         "geography_not_independently_verified")
        ev = deepcopy(EVENT)
        ev["location"]["countryCode"] = "DE"
        self.assertEqual(review(event=ev)["reason"],
                         "geography_not_independently_verified")
        unrelated = deepcopy(VENUE)
        unrelated["city"] = "Rouen"
        self.assertEqual(review(venue=unrelated)["reason"],
                         "geography_not_independently_verified")

    def test_french_overseas_geometry_and_local_time_explicitly_reviewed(self):
        lead = dict(LEAD, city="Le Gosier", venue="Médiathèque jeunesse",
                    source_url="https://openagenda.com/fr/gosier-test/events/12345678_fete-jeunesse")
        approved = {
            "agenda_slug": "gosier-test", "agenda_uid": "919191",
            "timezone": "America/Guadeloupe",
        }
        geo = {
            "city": "Le Gosier", "aliases": ["Médiathèque jeunesse"],
            "lat": 16.20547, "lng": -61.4895,
        }
        event = deepcopy(EVENT)
        event["timezone"] = "America/Guadeloupe"
        event["location"].update({
            "name": "Médiathèque jeunesse", "adminLevel4": "Le Gosier",
            "adminLevel1": "Guadeloupe", "adminLevel2": "Guadeloupe",
            "countryCode": "GP", "latitude": 16.20547,
            "longitude": -61.4895,
        })
        event["timings"][0] = {
            "begin": "2026-12-05T14:30:00-0400",
            "end": "2026-12-05T16:00:00-0400",
        }
        ok = review(lead=lead, agenda=approved, event=event, venue=geo)
        self.assertTrue(ok["source_evidence_structurally_valid"], ok["reason"])
        self.assertEqual(ok["explicit_local_times_for_candidate_day"], ["14:30"])
        self.assertFalse(ok["approval_granted"])
        event["location"]["countryCode"] = "MQ"
        self.assertEqual(review(lead=lead, agenda=approved, event=event,
                                venue=geo)["reason"],
                         "geography_not_independently_verified")
        event["location"]["countryCode"] = "GP"
        event["location"]["adminLevel2"] = "Martinique"
        self.assertEqual(review(lead=lead, agenda=approved, event=event,
                                venue=geo)["reason"],
                         "geography_not_independently_verified")

    def test_public_aggregate_refuses_arbitrary_reason_text(self):
        forged = review()
        forged["reason"] = "private city and source url disguised as failure"
        with self.assertRaisesRegex(ValueError, "invalid_source_report"):
            redacted_batch_report([forged])

    def test_timezone_offsets_dst_and_overseas_are_never_inferred(self):
        ev = deepcopy(EVENT)
        ev["timezone"] = "America/Guadeloupe"
        self.assertEqual(review(event=ev)["reason"],
                         "unreviewed_territory_timezone")
        ev = deepcopy(EVENT)
        ev["timings"][0]["begin"] = "2026-12-05T14:30:00+0200"
        self.assertEqual(review(event=ev)["reason"],
                         "time_offset_not_matching_reviewed_timezone")
        ev = deepcopy(EVENT)
        ev["timings"][0]["end"] = "2026-12-06T01:00:00+0100"
        self.assertEqual(review(event=ev)["reason"],
                         "overnight_timing_needs_separate_contract")

    def test_family_audience_age_claim_and_rights(self):
        ev = deepcopy(EVENT)
        ev["description"] = {"fr": "Sortie pour adultes uniquement"}
        self.assertEqual(review(event=ev)["reason"],
                         "family_audience_not_in_source_record")
        ev["age"] = {"min": 3, "max": 9}
        self.assertTrue(review(event=ev)["source_evidence_structurally_valid"])
        ev["age"] = {"min": 9, "max": 3}
        self.assertEqual(review(event=ev)["reason"], "invalid_age_claim")
        ev = deepcopy(EVENT)
        ev["rights"] = {}
        self.assertEqual(review(event=ev)["reason"], "source_rights_unknown")

    def test_recurring_oversized_duplicate_or_invalid_time_refused(self):
        ev = deepcopy(EVENT)
        ev["timings"].append(deepcopy(ev["timings"][0]))
        self.assertEqual(review(event=ev)["reason"], "duplicate_timing")
        ev = deepcopy(EVENT)
        ev["timings"] = ev["timings"] * 801
        self.assertEqual(review(event=ev)["reason"], "invalid_or_oversized_timings")
        ev = deepcopy(EVENT)
        ev["timings"][0]["begin"] = "2026-12-05T14:30:00"
        self.assertEqual(review(event=ev)["reason"], "invalid_timing_or_timezone")

    def test_expired_and_missing_agenda_registry_fail_closed(self):
        for bad in (None, {}, {"agenda_slug": "commune-test", "agenda_uid": "919191",
                              "timezone": "Africa/Paris"},
                    {"agenda_slug": "commune-test", "agenda_uid": "nope",
                     "timezone": "Europe/Paris"}):
            self.assertEqual(review(agenda=bad)["reason"],
                             "missing_or_unreviewed_source_registry")
        lead = dict(LEAD, date_start="2028-01-01", date_end="2028-01-01")
        self.assertEqual(review(lead=lead)["reason"],
                         "candidate_date_invalid_or_out_of_window")

    def test_batch_report_redacts_source_and_never_authorizes(self):
        positive = review()
        negative = review(event=dict(EVENT, state=1))
        r = redacted_batch_report([positive, negative])
        self.assertEqual(r["checked"], 2)
        self.assertEqual(r["approved_events"], 0)
        self.assertEqual(r["public_writes"], 0)
        s = json.dumps(r)
        self.assertNotIn("Villeurbanne", s)
        self.assertNotIn("12345678", s)
        self.assertNotIn("Fête jeunesse", s)
        with self.assertRaises(ValueError):
            redacted_batch_report([dict(positive, public_writes=1)])


class _MockHttp:
    def __init__(self, payload, redirected=False, status=200):
        self.payload = payload
        self.redirected = redirected
        self.status = status
        self.url = None
        self.request = None
    def __call__(self, request, timeout):
        self.request = request
        self.url = request.full_url
        self.timeout = timeout
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url + "/redirect" if self.redirected else self.url
    def read(self, size):
        self.size = size
        return json.dumps(self.payload).encode("utf-8")


class OA2ReadOnlyTransportTests(unittest.TestCase):
    def test_public_key_header_only_exact_pinned_https_route(self):
        network = _MockHttp(EVENT)
        row = read_direct_v2("919191", "12345678", "oa_pk_" + "x" * 30,
                             opener=network)
        self.assertEqual(row["uid"], 12345678)
        self.assertEqual(network.url,
                         "https://api.openagenda.com/v2/agendas/919191/events/12345678")
        self.assertEqual(network.timeout, 18)
        self.assertEqual(network.size, 600001)
        self.assertNotIn("oa_pk_", network.url)
        self.assertEqual(network.request.get_header("Key"), "oa_pk_" + "x" * 30)

    def test_secret_key_and_redirect_rejected(self):
        for key in ("oa_sk_" + "x" * 30, "", "oa_pk_\nmalicious", "public-legacy"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    read_direct_v2(919191, 12345678, key, opener=_MockHttp(EVENT))
        with self.assertRaises(ValueError):
            read_direct_v2("919191", "12345678", "oa_pk_" + "x" * 30,
                           opener=_MockHttp(EVENT, redirected=True))
        with self.assertRaises(ValueError):
            read_direct_v2("919191", "12345678", "oa_pk_" + "x" * 30,
                           opener=_MockHttp(EVENT, status=401))


if __name__ == "__main__":
    unittest.main()
