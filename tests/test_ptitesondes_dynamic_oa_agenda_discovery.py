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


    def test_opt_in_oa_source_without_any_ods_mirror_or_known_venue(self):
        from ptitesondes_openagenda_slug_discovery import SCHEMA as LOOKUP_SCHEMA
        source = dict(
            lead(uid="919191", city="", venue=""),
            collector="openagenda-v2",
            source_url=("https://openagenda.com/agendas-inconnus/"
                        "events/919191_eveil-musical-nouveau"),
        )
        rows, count, conflicts = candidate_batches(
            [source], [], DAY, include_openagenda_v2=True)
        self.assertEqual((len(rows), count, conflicts), (1, 1, 0))
        self.assertEqual(
            candidate_batches([source], [], DAY)[0], [])
        requests = []
        def no_ods(*args):
            raise AssertionError("ODS is not required for OA discovery")
        def slug_lookup(slug, key):
            requests.append(("slug", slug))
            return {
                "schema": LOOKUP_SCHEMA, "uid": 777888,
                "slug": slug,
                "status": "public_uid_slug_only_independent_ownership_pending",
                "independent_ownership_verified": False,
                "organizer_verified": False,
                "rights_reviewed": False, "publication_ready": False,
                "approval_granted": False, "publisher_connected": False,
                "public_writes": 0,
            }
        def read_agenda(uid, key):
            requests.append(("agenda", uid))
            return {"uid": uid, "slug": "agendas-inconnus"}
        def read_event(uid, event_uid, key):
            requests.append(("event", uid, event_uid))
            return event(uid=event_uid, city="Commune découverte",
                         venue="Place des petits concerts")
        result = discover_unconfigured_sources(
            rows, [], KEY, ods_get=no_ods, agenda_get=read_agenda,
            event_get=read_event, slug_lookup=slug_lookup)
        self.assertEqual(requests, [
            ("slug", "agendas-inconnus"), ("agenda", 777888),
            ("event", 777888, "919191")])
        self.assertEqual(result["counts"]["direct_unconfigured_agenda_event_concordant"], 1)
        self.assertEqual(result["new_agenda_candidates"][0]["agenda_uid"], 777888)
        self.assertFalse(result["new_agenda_candidates"][0]["rights_reviewed"])
        self.assertFalse(result["new_agenda_candidates"][0]["owner_independently_verified"])
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("additions", result)

    def test_missing_city_or_venue_keys_are_not_false_location_claims(self):
        from ptitesondes_openagenda_slug_discovery import SCHEMA as LOOKUP_SCHEMA
        source = dict(
            collector="openagenda-v2", external_id="919191",
            date_start="2026-12-12", date_end="2026-12-12",
            title="Spectacle sonore enfants",
            source_url="https://openagenda.com/new-agenda/events/919191_sound",
        )
        # A true absence must not turn into norm(None) == "none".
        rows, count, conflicts = candidate_batches(
            [source], [], DAY, include_openagenda_v2=True)
        self.assertEqual((len(rows), count, conflicts), (1, 1, 0))
        self.assertTrue(_direct_location_agrees(
            source, event("919191", city="Ville inconnue",
                          venue="Scène nouvelle"),
            allow_missing_lead_place=True))
        self.assertFalse(_direct_location_agrees(
            source, event("919191", city="Ville inconnue",
                          venue="Scène nouvelle")))
        lookup = {
            "schema": LOOKUP_SCHEMA, "uid": 777888, "slug": "new-agenda",
            "status": "public_uid_slug_only_independent_ownership_pending",
            "independent_ownership_verified": False,
            "organizer_verified": False, "rights_reviewed": False,
            "publication_ready": False, "approval_granted": False,
            "publisher_connected": False, "public_writes": 0,
        }
        result = discover_unconfigured_sources(
            rows, [], KEY,
            ods_get=lambda *args: (_ for _ in ()).throw(
                AssertionError("ODS forbidden")),
            agenda_get=lambda uid, key: {"uid": uid, "slug": "new-agenda"},
            event_get=lambda uid, event_uid, key: event(
                event_uid, city="Ville inconnue", venue="Scène nouvelle"),
            slug_lookup=lambda slug, key: lookup)
        self.assertEqual(len(result["new_agenda_candidates"]), 1)
        self.assertFalse(result["new_agenda_candidates"][0]["publisher_enabled"])
        self.assertEqual(result["public_writes"], 0)
        # Legacy ODS research still requires an actual city AND venue claim.
        ods_lead = dict(source, collector="opendatasoft-index")
        self.assertEqual(candidate_batches([ods_lead], [], DAY)[0], [])

    def test_oa_source_strict_uid_and_agenda_no_untrusted_api_permissions(self):
        from ptitesondes_openagenda_slug_discovery import SCHEMA as LOOKUP_SCHEMA
        source = dict(
            lead(uid="919191"), collector="openagenda-v2",
            source_url="https://openagenda.com/new-agenda/events/919191_music",
        )
        base = dict(
            schema=LOOKUP_SCHEMA, uid=777888, slug="new-agenda",
            status="public_uid_slug_only_independent_ownership_pending",
            independent_ownership_verified=False,
            organizer_verified=False, rights_reviewed=False,
            publication_ready=False, approval_granted=False,
            publisher_connected=False, public_writes=0,
        )
        for altered in (
            dict(base, approval_granted=True),
            dict(base, rights_reviewed=True),
            dict(base, organizer_verified=True),
            dict(base, uid=True),
            dict(base, uid=0),
            dict(base, public_writes=False),
            dict(base, slug="different"),
            dict(base, status="trusted"),
            dict(uid=777888, slug="new-agenda"),
        ):
            with self.subTest(altered=altered):
                calls = []
                result = discover_unconfigured_sources(
                    [source], [], KEY,
                    ods_get=lambda uid: (_ for _ in ()).throw(
                        AssertionError("ODS should not be invoked")),
                    agenda_get=lambda uid, key: (
                        calls.append("agenda") or
                        {"uid": uid, "slug": "new-agenda"}),
                    event_get=lambda *a: (
                        calls.append("event") or event("919191")),
                    slug_lookup=lambda slug, key: altered)
                self.assertEqual(result["new_agenda_candidates"], [])
                self.assertEqual(calls, [])
                self.assertEqual(result["public_writes"], 0)
        confirmed = discover_unconfigured_sources(
            [source], [], KEY,
            slug_lookup=lambda slug, key: base,
            agenda_get=lambda uid, key: {"uid": uid, "slug": "other"},
            event_get=lambda *a: (_ for _ in ()).throw(
                AssertionError("never read unknown agenda's event")))
        self.assertEqual(confirmed["new_agenda_candidates"], [])

    def test_oa_direct_source_cannot_resolve_wrong_venue_or_foreign_country(self):
        from ptitesondes_openagenda_slug_discovery import SCHEMA as LOOKUP_SCHEMA
        source = dict(
            lead(uid="919191"), collector="openagenda-v2",
            source_url="https://openagenda.com/new-agenda/events/919191_music",
        )
        result = {
            "schema": LOOKUP_SCHEMA, "uid": 777888, "slug": "new-agenda",
            "status": "public_uid_slug_only_independent_ownership_pending",
            "independent_ownership_verified": False,
            "organizer_verified": False, "rights_reviewed": False,
            "publication_ready": False, "approval_granted": False,
            "publisher_connected": False, "public_writes": 0,
        }
        for mutation in (
            {"name": "Autre lieu"},
            {"adminLevel4": "Other town"},
            {"countryCode": "DE"},
            {"countryCode": "ZZ"},
            {"longitude": 300.0},
            {"latitude": float("nan")},
        ):
            with self.subTest(mutation=mutation):
                ev = event(uid="919191")
                ev["location"].update(mutation)
                out = discover_unconfigured_sources(
                    [source], [], KEY,
                    slug_lookup=lambda slug, key: result,
                    agenda_get=lambda uid, key: {"uid": uid, "slug": "new-agenda"},
                    event_get=lambda uid, eid, key: ev,
                    ods_get=lambda *a: (_ for _ in ()).throw(
                        AssertionError("ODS not needed")),
                )
                self.assertEqual(out["new_agenda_candidates"], [])

    def test_french_pacific_territories_are_not_excluded_by_old_short_list(self):
        for country in ("FR", "GP", "MQ", "GF", "RE", "YT",
                        "PF", "NC", "WF", "PM", "BL", "MF"):
            with self.subTest(country=country):
                lead_item = lead()
                direct = event()
                direct["location"]["countryCode"] = country
                self.assertTrue(_direct_location_agrees(lead_item, direct))
        for country in ("DE", "GB", None, ""):
            with self.subTest(country=country):
                direct = event()
                direct["location"]["countryCode"] = country
                self.assertFalse(_direct_location_agrees(lead(), direct))

    def test_past_and_hostile_oa_candidates_are_not_a_path_to_admission(self):
        row = dict(
            lead(uid="919191"), collector="openagenda-v2",
            source_url="https://openagenda.com/new-agenda/events/919191_music",
        )
        for changed in (
            dict(row, source_url="https://openagenda.com.evil.example/new"),
            dict(row, external_id="999999"),
            dict(row, date_start="2026-01-01"),
            dict(row, collector="untrusted-collector"),
        ):
            with self.subTest(changed=changed):
                self.assertEqual(
                    candidate_batches([changed], [], DAY,
                                      include_openagenda_v2=True)[0], [])



if __name__ == "__main__":
    unittest.main()
