"""Offline adversarial checks for expanding discovered OA agendas, not publishing."""
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_dynamic_oa_agenda_discovery import (
    candidate_batches, discover_unconfigured_sources, _direct_location_agrees,
)

DAY = date(2026, 11, 20)
KEY = "oa_pk_public_read_test_key_123456789"
UID = "721"
AGENDA_UID = 777777


def lead(uid=UID, city="Ville de Test", venue="Place des concerts"):
    return {
        "collector": "opendatasoft-index",
        "external_id": str(uid),
        "title": "Conte musical pour enfants",
        "city": city, "venue": venue,
        "source_url": "https://openagenda.com/agenda-jeune-public/events/mon-concert-" + str(uid),
        "date_start": "2026-12-12",
        "date_end": "2026-12-12",
    }


def ods(uid=UID, agenda_uid=AGENDA_UID):
    return {
        "uid": str(uid), "canonicalurl": lead(uid)["source_url"],
        "location_name": "Place des concerts",
        "location_city": "Ville de Test",
        "location_countrycode": "FR",
        "location_coordinates": {"lat": 44.5, "lon": 2.25},
        "status": '{"id":1, "label":{"fr":"Programmé"}}',
        "originagenda_uid": str(agenda_uid),
    }


def event(uid=UID, city="Ville de Test", venue="Place des concerts"):
    return {
        "uid": int(uid), "state": 2, "status": 1, "removed": False,
        "attendanceMode": 1,
        "location": {
            "name": venue, "adminLevel4": city, "countryCode": "FR",
            "latitude": 44.5, "longitude": 2.25,
        },
    }


def read_agenda(uid, key):
    return {"uid": uid, "slug": "agenda-jeune-public"}


class DynamicAgendaDiscoveryTests(unittest.TestCase):
    def scan(self, leads=None, configured=None, ods_get=None,
             agenda_get=None, event_get=None, key=KEY):
        return discover_unconfigured_sources(
            [lead()] if leads is None else leads,
            [111111] if configured is None else configured, key,
            ods_get or (lambda uid: ods(uid)),
            agenda_get or read_agenda,
            event_get or (lambda aid, uid, key: event(uid)),
        )

    def test_new_source_agenda_and_event_are_both_consulted_without_publication(self):
        agendas, events = [], []
        def fetch_agenda(uid, key):
            agendas.append(uid)
            return read_agenda(uid, key)
        def fetch_event(agenda_uid, uid, key):
            events.append((agenda_uid, uid))
            return event(uid)
        result = self.scan(agenda_get=fetch_agenda, event_get=fetch_event)
        self.assertEqual(agendas, [AGENDA_UID])
        self.assertEqual(events, [(AGENDA_UID, UID)])
        self.assertEqual(len(result["new_agenda_candidates"]), 1)
        item = result["new_agenda_candidates"][0]
        self.assertEqual(item["agenda_uid"], AGENDA_UID)
        self.assertFalse(item["owner_independently_verified"])
        self.assertFalse(item["rights_reviewed"])
        self.assertFalse(item["publisher_enabled"])
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)

    def test_configured_agendas_do_not_consume_another_direct_event_read(self):
        event_get = Mock(side_effect=AssertionError("not required"))
        result = self.scan(configured=[AGENDA_UID], event_get=event_get)
        self.assertEqual(result["new_agenda_candidates"], [])
        self.assertEqual(result["counts"]["already_configured_agenda"], 1)
        event_get.assert_not_called()

    def test_bad_source_uid_or_canonical_url_is_never_registered(self):
        for record in (
            {**ods(), "uid": "9999"},
            {**ods(), "canonicalurl": "https://openagenda.com/other/events/x"},
            {**ods(), "location_city": "Autre ville"},
            {**ods(), "status": '{"id":2}'},
            {**ods(), "originagenda_uid": "unknown"},
        ):
            with self.subTest(record=record):
                result = self.scan(ods_get=lambda uid: record)
                self.assertEqual(result["new_agenda_candidates"], [])
                self.assertEqual(result["public_writes"], 0)

    def test_wrong_agenda_slug_uid_or_event_venue_is_refused(self):
        cases = (
            (lambda uid, key: {"uid": uid, "slug": "different"}, None),
            (lambda uid, key: {"uid": 999999, "slug": "agenda-jeune-public"}, None),
            (read_agenda, lambda aid, uid, key: event(uid, venue="Autre salle")),
            (read_agenda, lambda aid, uid, key: event("999999")),
        )
        for get_agenda, get_event in cases:
            with self.subTest(case=str(get_agenda)):
                result = self.scan(
                    agenda_get=get_agenda,
                    event_get=get_event or (lambda aid, uid, key: event(uid)))
                self.assertEqual(result["new_agenda_candidates"], [])

    def test_unknown_venue_does_not_need_legacy_registry(self):
        # "Place des concerts" is not in any curated VENUES registry.
        result = self.scan()
        self.assertEqual(len(result["new_agenda_candidates"]), 1)

    def test_direct_api_identity_cannot_certify_cancelled_or_remote_event(self):
        for attrs in ({"status": 4}, {"state": 1}, {"removed": True},
                      {"attendanceMode": 2}):
            with self.subTest(attrs=attrs):
                result = self.scan(event_get=lambda aid, uid, k:
                                   {**event(uid), **attrs})
                self.assertEqual(result["new_agenda_candidates"], [])

    def test_missing_public_read_key_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid_private_dynamic"):
            self.scan(key="")
        with self.assertRaisesRegex(ValueError, "invalid_private_dynamic"):
            self.scan(key="oa_sk_secret_cannot_be_used")

    def test_bounded_batches_cover_all_uids_and_skip_conflicts(self):
        records = [lead(uid=str(1000 + i)) for i in range(85)]
        batches = [candidate_batches(records, [111], DAY, i)
                   for i in range(3)]
        self.assertEqual([len(x[0]) for x in batches], [40, 40, 5])
        self.assertEqual([x[1] for x in batches], [3, 3, 3])
        self.assertEqual(len({
            lead["external_id"] for batch, _, _ in batches for lead in batch
        }), 85)
        with self.assertRaisesRegex(ValueError, "out_of_range"):
            candidate_batches(records, [111], DAY, 3)
        conflict = {**records[0], "venue": "Autre lieu"}
        new = candidate_batches(records + [conflict], [111], DAY, 0)
        self.assertEqual(new[2], 1)
        self.assertNotIn(records[0]["external_id"], {
            row["external_id"] for row in new[0]})

    def test_days_and_untrusted_source_shape_filtered_without_location_whitelist(self):
        records = [
            lead(),
            {**lead("722"), "date_start": "2026-10-10"},
            {**lead("723"), "source_url": "https://evil.example/event"},
            {**lead("724"), "external_id": "not-a-uid"},
            {**lead("725"), "collector": "fake"},
        ]
        rows, count, conflicts = candidate_batches(records, [111], DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(count, 1)
        self.assertEqual(conflicts, 0)


if __name__ == "__main__":
    unittest.main()
