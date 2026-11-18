"""Offline adversarial tests: no private backlog, credentials or publisher."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_preintegration import (
    SCHEMA, agenda_identity_for_review, independently_linked_agenda,
    group_multi_day, ods_fallback_preflight,
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


if __name__ == "__main__":
    unittest.main()
