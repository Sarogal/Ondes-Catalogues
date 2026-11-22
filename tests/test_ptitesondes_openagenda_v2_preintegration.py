"""Offline adversarial tests: no private backlog, credentials or publisher."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_preintegration import (
    SCHEMA, agenda_identity_for_review, independently_linked_agenda,
    group_multi_day, ods_fallback_preflight, review_missing_mirror_source,
)

REGISTRY = {
    "agenda_uid": "919191", "agenda_slug": "ville-test",
    "timezone": "Europe/Paris",
    "institution_url": "https://www.institution.example.org/",
    "authority_reference_url": "https://www.institution.example.org/agenda",
}
API_AGENDA = {"uid": 919191, "slug": "ville-test", "official": 1}
SLOTS = [
    {"begin": "2026-12-05T14:30:00+0100", "end": "2026-12-05T15:30:00+0100"},
    {"begin": "2026-12-06T14:30:00+0100", "end": "2026-12-06T15:30:00+0100"},
    {"begin": "2026-12-07T14:30:00+0100", "end": "2026-12-07T15:30:00+0100"},
]
EVENT = {"uid": 12345678, "timezone": "Europe/Paris", "timings": SLOTS}
ORGANIZER = "https://programme.example.org/"
DIRECT = {
    "schema": "ptitesondes.openagenda_v2_direct_source_evidence.v1",
    "source_evidence_structurally_valid": True,
    "api_family_audience_confirmed": True,
    "approval_granted": False, "public_writes": 0,
}


class AgendaIdentityContract(unittest.TestCase):
    def test_exact_identity_is_not_owner_attestation(self):
        state = agenda_identity_for_review(API_AGENDA, REGISTRY)
        self.assertTrue(state["identity_consistent"])
        self.assertFalse(state["ownership_attested"])
        self.assertFalse(state["publishing_authorized"])

    def test_institutional_link_requires_independent_exact_html_anchor(self):
        state = agenda_identity_for_review(API_AGENDA, REGISTRY)
        yes = {"url": REGISTRY["authority_reference_url"],
               "text": '<a href="https://openagenda.com/fr/ville-test">Agenda</a>'}
        self.assertTrue(independently_linked_agenda(state, REGISTRY, yes))
        for html in (
            "https://openagenda.com/fr/ville-test",
            '<a href="https://openagenda.com/fr/ville-test-evil">Agenda</a>',
            '<a href="https://openagenda.com.evil.test/fr/ville-test">Agenda</a>',
            '<a href="http://openagenda.com/fr/ville-test">Agenda</a>',
        ):
            with self.subTest(html=html):
                self.assertFalse(independently_linked_agenda(
                    state, REGISTRY,
                    {"url": REGISTRY["authority_reference_url"], "text": html}))
        self.assertFalse(independently_linked_agenda(
            state, REGISTRY, {"url": "https://evil.test/agenda", "text": yes["text"]}))

    def test_mismatched_uid_slug_and_untrusted_registry_fail_closed(self):
        variants = [
            ({"uid": 919192, "slug": "ville-test"}, REGISTRY),
            ({"uid": 919191, "slug": "ville-test2"}, REGISTRY),
            (API_AGENDA, dict(REGISTRY, institution_url="http://www.institution.example.org/")),
            (API_AGENDA, dict(REGISTRY, authority_reference_url="https://evil.test/agenda")),
            (API_AGENDA, dict(REGISTRY, agenda_uid="919192")),
            (API_AGENDA, dict(REGISTRY, timezone="Africa/Paris")),
            (API_AGENDA, {}),
        ]
        for remote, entry in variants:
            with self.subTest(remote=remote, entry=entry):
                self.assertFalse(agenda_identity_for_review(remote, entry)[
                    "identity_consistent"])


class MultiDayContract(unittest.TestCase):
    def test_one_day_explicit_stays_nonpublishable(self):
        e = dict(EVENT, timings=[SLOTS[0]])
        x = group_multi_day(e)
        self.assertEqual(x["kind"], "one_day_explicit_slots")
        self.assertFalse(x["daily_cards_authorized"])
        self.assertFalse(x["publication_authorized"])

    def test_29_day_exhibition_is_not_29_separate_cards(self):
        slots = []
        for d in range(1, 30):
            slots.append({"begin": f"2026-12-{d:02d}T10:00:00+0100",
                          "end": f"2026-12-{d:02d}T18:00:00+0100"})
        ev = dict(EVENT, timings=slots)
        unknown = group_multi_day(ev)
        self.assertEqual(unknown["explicit_day_count"], 29)
        self.assertEqual(unknown["kind"], "multi_day_unresolved")
        exhibition = {
            "event_uid": "12345678",
            "presentation": "continuous_period",
            "date_start": "2026-12-01", "date_end": "2026-12-29",
            "source_url": "https://programme.example.org/exposition",
        }
        x = group_multi_day(ev, exhibition, reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(x["kind"], "continuous_period_for_editorial_review")
        self.assertFalse(x["daily_cards_authorized"])
        self.assertFalse(x["publication_authorized"])

    def test_official_short_window_does_not_certify_entire_exhibition(self):
        # Generic realistic pattern: one multi-day UID spans December to
        # January, whereas a first-party programme attests only four days.
        # The fixture asserts no inferred schedules or daily publications.
        first = date(2026, 12, 5)
        event = dict(EVENT, timings=[])
        for n in range(30):
            day = (first + timedelta(days=n)).isoformat()
            event["timings"].append({
                "begin": day + "T10:00:00+0100",
                "end": day + "T18:00:00+0100",
            })
        limited = {
            "event_uid": "12345678", "presentation": "continuous_period",
            "date_start": "2026-12-05", "date_end": "2026-12-08",
            "source_url": "https://programme.example.org/officiel",
        }
        x = group_multi_day(event, limited,
                            reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(x["kind"],
                         "partial_continuous_period_for_editorial_review")
        self.assertEqual(x["explicit_day_count"], 30)
        self.assertEqual(x["independently_confirmed_window_days"], 4)
        self.assertFalse(x["daily_cards_authorized"])
        self.assertFalse(x["publication_authorized"])
        self.assertEqual(group_multi_day(event, limited)["kind"],
                         "multi_day_unresolved")
        suspect = dict(limited, date_end="2027-01-07")
        self.assertEqual(
            group_multi_day(event, suspect,
                            reviewed_organizer_origin=ORGANIZER)["kind"],
            "multi_day_unresolved",
        )

    def test_continuous_period_requires_matching_range_and_official_origin(self):
        source = {"event_uid": "12345678", "presentation": "continuous_period",
                  "date_start": "2026-12-05", "date_end": "2026-12-07",
                  "source_url": "https://programme.example.org/calendrier"}
        yes = group_multi_day(EVENT, source, reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(yes["kind"], "continuous_period_for_editorial_review")
        for item, expected_origin in (
            (dict(source, date_end="2026-12-08"), ORGANIZER),
            (dict(source, event_uid="00000001"), ORGANIZER),
            (dict(source, source_url="https://evil.test/programme"), ORGANIZER),
            (source, "https://evil.test/"),
            (source, None),
        ):
            with self.subTest(item=item, expected_origin=expected_origin):
                x = group_multi_day(EVENT, item, expected_origin)
                self.assertEqual(x["kind"], "multi_day_unresolved")

    def test_series_requires_all_exact_organizer_slots(self):
        source = {
            "event_uid": 12345678,
            "presentation": "separate_sessions",
            "source_url": "https://programme.example.org/horaires",
            "confirmed_slots": deepcopy(SLOTS),
        }
        x = group_multi_day(EVENT, source, reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(x["kind"], "separate_sessions_for_editorial_review")
        self.assertFalse(x["daily_cards_authorized"])
        x = group_multi_day(EVENT, dict(source, confirmed_slots=SLOTS[:2]),
                            reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(x["kind"], "multi_day_unresolved")
        x = group_multi_day(EVENT, dict(source, confirmed_slots=SLOTS +
                            [{"begin": "2026-12-08T14:30:00+0100",
                              "end": "2026-12-08T15:30:00+0100"}]),
                            reviewed_organizer_origin=ORGANIZER)
        self.assertEqual(x["kind"], "multi_day_unresolved")

    def test_no_inferred_slots_overlap_wrong_offset_or_duplicates(self):
        for slots in (
            [dict(SLOTS[0], begin="2026-12-05")],
            [SLOTS[0], deepcopy(SLOTS[0])],
            [dict(SLOTS[0], end="2026-12-06T15:30:00+0100")],
            [dict(SLOTS[0], begin="2026-12-05T14:30:00+0200")],
            [SLOTS[0], {"begin": "2026-12-05T15:00:00+0100",
                        "end": "2026-12-05T16:00:00+0100"}],
        ):
            with self.subTest(slots=slots):
                self.assertEqual(group_multi_day(dict(EVENT, timings=slots))["kind"],
                                 "unverified")

    def test_french_overseas_timezone_without_paris_inference(self):
        event = {
            "uid": 55943123, "timezone": "Indian/Reunion",
            "timings": [
                {"begin": "2026-12-05T14:00:00+0400",
                 "end": "2026-12-05T16:00:00+0400"},
            ],
        }
        self.assertEqual(group_multi_day(event)["kind"], "one_day_explicit_slots")
        event["timings"][0]["begin"] = "2026-12-05T14:00:00+0100"
        self.assertEqual(group_multi_day(event)["kind"], "unverified")


class FallbackContract(unittest.TestCase):
    def ok(self, **kwargs):
        defaults = dict(ods_state="uid_absent",
                        direct_result=deepcopy(DIRECT),
                        agenda_identity=agenda_identity_for_review(API_AGENDA, REGISTRY),
                        grouping=group_multi_day(dict(EVENT, timings=[SLOTS[0]])),
                        historic_uid_exists=False, independently_linked=True)
        defaults.update(kwargs)
        return ods_fallback_preflight(**defaults)

    def test_only_missing_or_unavailable_ods_can_be_proposed(self):
        for status in ("found", "conflicting", "malformed", None, "success"):
            self.assertEqual(self.ok(ods_state=status)["route"], "hold")
        self.assertEqual(self.ok(ods_state="temporary_unavailable")["route"], "hold")
        self.assertEqual(self.ok(ods_state="uid_absent")["route"],
                         "direct_source_candidate_for_remaining_gates")
        # A forged first-party report cannot waive agenda origin verification.
        x = self.ok(independently_linked=False, first_party_session_evidence={
            "schema": "ptitesondes.oa2.independent_organizer_session.v1",
            "official_session_evidence_consistent": True,
            "approval_granted": True, "public_writes": 0,
        })
        self.assertEqual(x["route"], "hold")

    def test_institution_historic_unknown_and_multi_day_block(self):
        for changes in (
            {"independently_linked": False},
            {"historic_uid_exists": True},
            {"historic_uid_exists": None},
            {"grouping": group_multi_day(EVENT)},
            {"agenda_identity": {"identity_consistent": True}},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.ok(**changes)["route"], "hold")

    def test_forged_source_does_not_grant_routing_or_publishing(self):
        variants = [
            dict(DIRECT, schema="forged"),
            dict(DIRECT, source_evidence_structurally_valid=False),
            dict(DIRECT, approval_granted=True),
            dict(DIRECT, public_writes=1),
        ]
        for bad in variants:
            with self.subTest(bad=bad):
                self.assertEqual(self.ok(direct_result=bad)["route"], "hold")
        approved = self.ok()
        self.assertEqual(approved["route"], "direct_source_candidate_for_remaining_gates")
        self.assertFalse(approved["approval_granted"])
        self.assertFalse(approved["publisher_connected"])
        self.assertEqual(approved["public_writes"], 0)
        self.assertNotIn("additions", approved)



class MissingMirrorDirectRoutingContract(unittest.TestCase):
    """Real routing code, offline providers; no publisher, files or secrets."""

    def sample(self):
        lead = {
            "collector": "openagenda-v2",
            "source_url":
                "https://openagenda.com/fr/ville-test/events/12345678_spectacle",
            "external_id": "12345678",
            "date_start": "2026-12-05", "date_end": "2026-12-05",
            "title": "Spectacle jeunesse",
            "city": "Ville fictive", "venue": "Place des familles",
        }
        event = {
            "uid": 12345678, "state": 2, "status": 1, "removed": False,
            "attendanceMode": 1, "timezone": "Europe/Paris",
            "title": {"fr": "Spectacle jeunesse"},
            "description": {"fr": "Spectacle pour enfants et familles"},
            "rights": {
                "license": {"id": "etalab-2.0"},
                "licensor": {"name": "Organisateur de test"},
            },
            "location": {
                "name": "Place des familles", "adminLevel4": "Ville fictive",
                "countryCode": "FR", "latitude": 45.75, "longitude": 4.90,
            },
            "timings": [{
                "begin": "2026-12-05T14:30:00+0100",
                "end": "2026-12-05T15:30:00+0100",
            }],
        }
        # Independently documented location, not a closed list of venues.
        venue = {
            "city": "Ville fictive", "aliases": ["Place des familles"],
            "lat": 45.75, "lng": 4.90,
        }
        return lead, event, venue

    def route(self, *, lead=None, event=None, venue=None, state="uid_absent",
              catalog=None, agenda=None, page=None):
        s_lead, s_event, s_venue = self.sample()
        lead = deepcopy(s_lead if lead is None else lead)
        event = deepcopy(s_event if event is None else event)
        venue = deepcopy(s_venue if venue is None else venue)
        registry = dict(REGISTRY, agenda_slug="ville-test")
        agenda = agenda if agenda is not None else {
            "uid": 919191, "slug": "ville-test"}
        page = page if page is not None else {
            "url": REGISTRY["authority_reference_url"],
            "text": '<a href="https://openagenda.com/fr/ville-test">Agenda officiel</a>',
        }
        return review_missing_mirror_source(
            lead, registry, venue, date(2026, 11, 21), "dummy-test-read-key",
            [] if catalog is None else catalog,
            ods_probe=lambda uid: state,
            agenda_reader=lambda uid, key: agenda,
            event_reader=lambda uid, event_uid, key: event,
            institutional_page=page,
        )

    def test_mirror_absent_direct_single_day_routes_without_approval(self):
        routed = self.route()
        self.assertEqual(routed["route"],
                         "direct_source_candidate_for_remaining_gates")
        self.assertFalse(routed["publisher_connected"])
        self.assertFalse(routed["approval_granted"])
        self.assertEqual(routed["public_writes"], 0)
        self.assertNotIn("additions", routed)

    def test_ods_outage_nonunique_or_contradiction_cannot_trigger_direct(self):
        for state in ("uid_unique", "uid_nonunique", "network_error",
                      "http_429", "http_500", "invalid_json_or_schema",
                      "unexpected_uid", "probe_unavailable"):
            with self.subTest(state=state):
                self.assertEqual(self.route(state=state)["reason"],
                                 "ods_unavailable_present_or_conflicting")

    def test_cancelled_wrong_uid_place_and_source_never_route(self):
        lead, event, venue = self.sample()
        cases = [
            {"event": dict(event, status=0)},
            {"event": dict(event, removed=True)},
            {"event": dict(event, uid=12345679)},
            {"event": dict(event, location=dict(event["location"],
                                                 latitude=10.0))},
            {"event": dict(event, timings=[])},
            {"lead": dict(lead, source_url=
                          "https://openagenda.com.evil.test/fr/ville-test/events/12345678_spectacle")},
            {"lead": dict(lead, collector="untrusted-source")},
            {"agenda": {"uid": 919192, "slug": "ville-test"}},
            {"page": {"url": "https://evil.test", "text":
                       '<a href="https://openagenda.com/fr/ville-test">fake</a>'}},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.route(**data)["route"], "hold")

    def test_existing_published_uid_day_and_matching_range_are_held(self):
        lead, event, venue = self.sample()
        published = [{
            "id": "openagenda-12345678-2026-12-05",
            "title": "Spectacle jeunesse", "city": "Ville fictive",
            "venue": "Place des familles",
            "date_start": "2026-12-05", "date_end": "2026-12-06",
        }]
        self.assertEqual(self.route(catalog=published)["reason"],
                         "already_published")
        published[0]["id"] = "historic-show"
        self.assertEqual(self.route(catalog=published)["reason"],
                         "already_published")

    def test_five_real_sessions_are_not_rejected_by_arbitrary_threshold(self):
        _, event, _ = self.sample()
        event["timings"] = [{
            "begin": f"2026-12-05T{hour:02d}:00:00+0100",
            "end": f"2026-12-05T{hour:02d}:30:00+0100",
        } for hour in range(10, 15)]
        self.assertEqual(self.route(event=event)["route"],
                         "direct_source_candidate_for_remaining_gates")

    def test_many_days_stay_grouping_review_not_daily_inventions(self):
        _, event, _ = self.sample()
        event["timings"].append({
            "begin": "2026-12-06T14:30:00+0100",
            "end": "2026-12-06T15:30:00+0100",
        })
        self.assertEqual(self.route(event=event)["reason"],
                         "multi_day_requires_grouping")

    def test_other_french_territory_clocks_have_full_preintegration_support(self):
        # Same eight zones accepted by the direct OA proof's IANA audit.
        cases = [
            ("Pacific/Tahiti", "-1000"),
            ("Pacific/Marquesas", "-0930"),
            ("Pacific/Gambier", "-0900"),
            ("Pacific/Noumea", "+1100"),
            ("Pacific/Wallis", "+1200"),
            ("America/Miquelon", "-0300"),
            ("America/St_Barthelemy", "-0400"),
            ("America/Marigot", "-0400"),
        ]
        for zone, offset in cases:
            with self.subTest(zone=zone):
                event = {
                    "uid": 12345678, "timezone": zone,
                    "timings": [{
                        "begin": "2026-12-05T14:00:00" + offset,
                        "end": "2026-12-05T15:00:00" + offset,
                    }],
                }
                self.assertEqual(group_multi_day(event)["kind"],
                                 "one_day_explicit_slots")
                wrong = deepcopy(event)
                wrong["timings"][0]["begin"] = "2026-12-05T14:00:00+0100"
                self.assertEqual(group_multi_day(wrong)["kind"], "unverified")


if __name__ == "__main__":
    unittest.main()
