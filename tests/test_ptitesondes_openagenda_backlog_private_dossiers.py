"""Existing ODS/official OA backlog may request first-party UID verification."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_open_world_release_rehearsal import TODAY, DAY, AGENDA, TITLE, oa_event
from test_ptitesondes_open_world_patch_bridge import private_patch, readers
from ptitesondes_openagenda_backlog_private_dossiers import (
    backlog_identity, live_research_dossier, read_agenda_by_slug,
    build_backlog_dossiers, MAX_ATTEMPTS, reclaim_live_confirmed_on_demand,
    deadline_aware_backlog_batch, fair_backlog_identity_order,
)
from ptitesondes_open_world_patch_bridge import merge_verified_open_world


def clue(uid=999401, day=DAY.isoformat(), source="opendatasoft-index"):
    return {
        "collector": source, "external_id": str(uid),
        "source_url":
            "https://openagenda.com/agenda-nouveau-organisateur/events/"
            + str(uid) + "_conte-musical",
        "title": TITLE, "date_start": day,
        "city": "Nouvelleville", "venue": "Nouveau théâtre",
        "reason": "Piste non vérifiée",
    }


class Response:
    status = 200

    def __init__(self, url, data):
        self.url, self.data = url, data

    def geturl(self):
        return self.url

    def read(self, n):
        return json.dumps(self.data).encode("utf-8")[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BacklogFirstPartyTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = base()
        self.patch = private_patch(self.catalogue, queue=[])
        self.key = "oa_pk_open_world_release_rehearsal_test"

    def build(self, rows, **kwargs):
        kwargs.setdefault("agenda_reader", lambda slug, _: AGENDA)
        kwargs.setdefault("event_reader", lambda *args: oa_event())
        return build_backlog_dossiers(
            rows, self.patch, self.catalogue, TODAY, self.key, **kwargs)

    def test_same_slot_retries_rotate_persisted_transient_failures(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        rows = [clue(uid=800000+i) for i in range(60)]
        batches = []
        for _ in range(3):
            reads = []
            def unavailable(agenda_uid, uid, key):
                reads.append(uid)
                raise TimeoutError("transient")
            result, counts = self.build(rows, batch_index=0,
                refusal_memory=memory, as_of_utc=now, event_reader=unavailable)
            self.assertEqual(counts["clues_examined"], MAX_ATTEMPTS)
            self.assertEqual(result["open_world_research"], [])
            self.assertFalse(result["safe_to_publish"])
            self.assertEqual(memory["entries"], {})
            batches.append(set(reads))
            # Simulate a different runner with only persisted private JSON.
            memory = json.loads(json.dumps(memory))
        self.assertFalse(batches[0] & batches[1])
        self.assertEqual(len(set.union(*batches)), 60)
        self.assertEqual(len(memory["attempts"]), 60)

    def test_persistent_rotation_preserves_urgent_budget_and_changed_clue(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        urgent = [clue(uid=900000+i,
            day=(TODAY+timedelta(days=2)).isoformat()) for i in range(20)]
        ordinary = [clue(uid=800000+i) for i in range(60)]
        rows = urgent + ordinary
        batches = []
        for turn in range(2):
            reads = []
            def unavailable(agenda_uid, uid, key):
                reads.append(uid)
                raise TimeoutError("transient")
            self.build(rows, batch_index=0, refusal_memory=memory,
                       as_of_utc=now, event_reader=unavailable)
            batches.append(set(reads))
            self.assertEqual(sum(uid >= 900000 for uid in reads), 8)
        self.assertFalse(batches[0] & batches[1])
        changed_uid = min(uid for uid in batches[0] if uid < 900000)
        changed = [dict(row, reason="updated") if
                   row["external_id"] == str(changed_uid) else row for row in rows]
        reads = []
        def unavailable(agenda_uid, uid, key):
            reads.append(uid)
            raise TimeoutError("transient")
        self.build(changed, batch_index=0, refusal_memory=memory,
                   as_of_utc=now, event_reader=unavailable)
        self.assertIn(changed_uid, reads)
        self.assertEqual(sum(uid >= 900000 for uid in reads), 8)

    def test_attempt_memory_migrates_and_rejects_untrusted_recency(self):
        from ptitesondes_editorial_refusal_memory import empty_memory, fresh_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        old = empty_memory()
        old.pop("attempts")
        old.pop("attempt_sequence")
        result = fresh_memory(old, now)
        self.assertEqual(result["attempts"], {})
        self.assertEqual(result["attempt_sequence"], 0)
        old.update(attempt_sequence=3, attempts={
            "a"*64: 2, "b"*64: 4, "c"*64: -1, "d"*64: True, "bad": 1})
        result = fresh_memory(old, now)
        self.assertEqual(result["attempts"], {"a"*64: 2})
        self.assertEqual(result["attempt_sequence"], 3)

    def test_ods_and_existing_oa_sources_are_untrusted_but_eligible(self):
        for collector in ("opendatasoft-index", "openagenda-v2"):
            with self.subTest(collector=collector):
                row = clue(source=collector)
                result, counts = self.build([row])
                self.assertEqual(counts["new_dossiers"], 1)
                self.assertEqual(len(result["open_world_research"]), 1)
                self.assertEqual(result["additions"], [])
                self.assertFalse(result["safe_to_publish"])
                dossier = result["open_world_research"][0]
                self.assertEqual(dossier["lead"]["event_uid"], 999401)
                self.assertEqual(dossier["lead"]["agenda_uid"], AGENDA["uid"])
                self.assertEqual(dossier["date_start"], DAY.isoformat())
                self.assertEqual(dossier["official_event_url"],
                                 "https://openagenda.com/agenda-nouveau-organisateur/events/999401")

    def test_editorial_refusal_is_reversible_and_never_an_approval(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        row = dict(clue(), title="Concert de musique")
        event = dict(oa_event(), title={"fr": row["title"]},
                     description={"fr": "Concert de musique classique"}, age=None)
        original = deepcopy(row)
        result, counts = self.build([row], refusal_memory=memory,
                                    as_of_utc=now, event_reader=lambda *_: event)
        self.assertEqual(counts["editorial_new_live_refusals"], 1)
        self.assertEqual(result["open_world_research"], [])
        self.assertEqual(row, original)
        self.assertEqual(result["additions"], [])
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(len(memory["entries"]), 1)
        result, counts = self.build([row], refusal_memory=memory,
                                    as_of_utc=now + timedelta(hours=1),
                                    event_reader=lambda *_: self.fail("Cached refusal"))
        self.assertEqual(counts["editorial_cached_backlog_deferred"], 1)
        updated = dict(event, age={"min": 3, "max": 12},
                       description={"fr": "Concert de musique pour enfants"})
        result, counts = self.build([row], refusal_memory=memory,
                                    as_of_utc=now + timedelta(hours=12),
                                    event_reader=lambda *_: updated)
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertEqual(result["additions"], [])
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(memory["entries"], {})

    def test_itinerant_availability_is_reversible_private_deferral(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        row = dict(clue(), title="Contes musicaux pour bébés")
        original = deepcopy(row)
        event = dict(oa_event(), title={"fr": row["title"]},
                     description={"fr": "Spectacle pour les enfants. Dispositif itinérant dans différentes structures."},
                     conditions={"fr": "Renseignements auprès du musée"},
                     timings=[{"begin": DAY.isoformat() + "T08:00:00+01:00",
                               "end": DAY.isoformat() + "T19:00:00+01:00"}])
        first, counts = self.build([row], refusal_memory=memory,
                                   as_of_utc=now, event_reader=lambda *_: event)
        self.assertEqual(counts["editorial_new_live_refusals"], 1)
        self.assertEqual(first["open_world_research"], [])
        self.assertEqual(first["additions"], [])
        self.assertEqual(row, original)
        self.assertEqual(next(iter(memory["entries"].values()))["reason"],
                         "oa_direct_itinerant_availability_review")
        _, counts = self.build([row], refusal_memory=memory,
                               as_of_utc=now + timedelta(hours=1),
                               event_reader=lambda *_: self.fail("Unexpired refusal"))
        self.assertEqual(counts["editorial_cached_backlog_deferred"], 1)
        updated = dict(event, timings=[{"begin": DAY.isoformat() + "T10:00:00+01:00",
                                      "end": DAY.isoformat() + "T11:00:00+01:00"}])
        final, counts = self.build([row], refusal_memory=memory,
                                   as_of_utc=now + timedelta(hours=12),
                                   event_reader=lambda *_: updated)
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertEqual(final["additions"], [])
        self.assertFalse(final["safe_to_publish"])
        self.assertEqual(memory["entries"], {})

    def test_changed_collector_hint_invalidates_deferral_without_expiry(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        row = dict(clue(), title="Concert de musique")
        event = dict(oa_event(), title={"fr": row["title"]},
                     description={"fr": "Concert de musique classique"}, age=None)
        self.build([row], refusal_memory=memory, as_of_utc=now,
                   event_reader=lambda *_: event)
        self.assertEqual(len(memory["entries"]), 1)
        changed = dict(row, reason="Programme mis à jour")
        result, counts = self.build([changed], refusal_memory=memory,
            as_of_utc=now + timedelta(hours=1), event_reader=lambda *_:
            dict(event, age={"min": 3, "max": 12},
                 description={"fr": "Concert de musique pour enfants"}))
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertEqual(counts["editorial_cached_backlog_deferred"], 0)

    def test_transient_or_unverified_source_is_not_cached(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        def failed(*_):
            raise TimeoutError("network")
        _, counts = self.build([clue()], refusal_memory=memory,
                               as_of_utc=now, event_reader=failed)
        self.assertEqual(counts["held_for_publisher_or_network"], 1)
        self.assertEqual(memory["entries"], {})
        _, counts = self.build([clue()], refusal_memory=memory,
                               as_of_utc=now, event_reader=lambda *_: dict(oa_event(), uid=22))
        self.assertEqual(counts["held_for_publisher_or_network"], 1)
        self.assertEqual(memory["entries"], {})

    def test_existing_refusal_frees_queue_slot_only_when_history_retains_clue(self):
        from ptitesondes_editorial_refusal_memory import empty_memory
        now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        memory = empty_memory()
        row = dict(clue(), title="Concert de musique")
        event = dict(oa_event(), title={"fr": row["title"]},
                     description={"fr": "Concert de musique classique"}, age=None)
        first, _ = self.build([row], event_reader=lambda *_: event)
        self.assertEqual(len(first["open_world_research"]), 1)
        result, counts = build_backlog_dossiers(
            [row], first, self.catalogue, TODAY, self.key,
            agenda_reader=lambda *_: AGENDA, event_reader=lambda *_: event,
            refusal_memory=memory, as_of_utc=now)
        self.assertEqual(counts["editorial_live_queue_deferred"], 1)
        self.assertEqual(result["open_world_research"], [])
        preserved, _ = build_backlog_dossiers(
            [], first, self.catalogue, TODAY, self.key,
            agenda_reader=lambda *_: self.fail("No history"),
            event_reader=lambda *_: self.fail("No history"),
            refusal_memory=memory, as_of_utc=now)
        self.assertEqual(preserved["open_world_research"], first["open_world_research"])

    def test_no_second_source_needed_for_real_publisher_merge(self):
        patch, counts = self.build([clue()])
        kwargs = readers()
        for method in ("official_reader", "directory_reader", "ign_reader", "osm_reader"):
            kwargs[method] = lambda *args: self.fail("Unneeded second source")
        result, audit, report = merge_verified_open_world(
            self.catalogue, self.catalogue, patch, TODAY, self.key, **kwargs)
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["publisher_accepted_new"], 1)
        self.assertEqual(result["events"][-1]["id"],
                         "openagenda-999401-" + DAY.isoformat())

    def test_legacy_clue_cannot_supply_event_or_agenda_identity(self):
        row = clue()
        for url in (
            "https://other.example/agenda-nouveau-organisateur/events/999401_conte-musical",
            "http://openagenda.com/agenda-nouveau-organisateur/events/999401_conte-musical",
            "https://openagenda.com/agenda-nouveau-organisateur/events/999402_conte-musical",
            "https://openagenda.com/agenda-nouveau-organisateur/events/999401_conte-musical?redirect=1",
            "https://openagenda.com@evil.example/agenda-nouveau-organisateur/events/999401",
        ):
            with self.subTest(url=url):
                self.assertIsNone(backlog_identity(dict(row, source_url=url), TODAY))
        self.assertIsNone(backlog_identity(dict(row, external_id="999401x"), TODAY))
        self.assertIsNone(backlog_identity(dict(row, collector="unknown"), TODAY))
        self.assertIsNone(backlog_identity(dict(row, date_start=(TODAY-timedelta(days=1)).isoformat()), TODAY))

    def test_official_slug_filter_is_pinned_and_requires_exact_single_result(self):
        calls = []
        def opener(req, timeout):
            calls.append((req.full_url, timeout, req.get_header("Key")))
            return Response(req.full_url, {"agendas": [AGENDA]})
        got = read_agenda_by_slug(AGENDA["slug"], self.key, opener=opener)
        self.assertEqual(got["uid"], AGENDA["uid"])
        self.assertEqual(urlsplit(calls[0][0]).hostname, "api.openagenda.com")
        self.assertEqual(parse_qs(urlsplit(calls[0][0]).query)["slug"], [AGENDA["slug"]])
        self.assertEqual(calls[0][1], 20)
        for records in ([], [dict(AGENDA, slug="other")], [AGENDA, AGENDA],
                        [dict(AGENDA, uid="not-an-int")]):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    read_agenda_by_slug(AGENDA["slug"], self.key,
                        opener=lambda req, timeout: Response(req.full_url, {"agendas": records}))

    def test_envelopes_and_inexact_live_uid_never_override_source(self):
        identity = backlog_identity(clue(), TODAY)
        self.assertIsNotNone(live_research_dossier(identity, TODAY, AGENDA,
                                                    {"event": oa_event()}))
        for bad in (
            {"uid": 22, "event": oa_event()},
            {"event": dict(oa_event(), uid=22)},
            dict(oa_event(), uid=22),
            dict(oa_event(), timings=[]),
            dict(oa_event(), state=1),
            dict(oa_event(), title={"fr": "Spectacle différent"}),
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(live_research_dossier(identity, TODAY, AGENDA, bad))
        self.assertIsNone(live_research_dossier(identity, TODAY,
                          dict(AGENDA, slug="other"), oa_event()))

    def test_published_and_existing_queued_occurrences_are_not_duplicated(self):
        published = deepcopy(self.catalogue)
        published["events"].append({"id": "openagenda-999401-" + DAY.isoformat()})
        combined, counts = build_backlog_dossiers(
            [clue()], self.patch, published, TODAY, self.key,
            agenda_reader=lambda *a: self.fail("Must skip published"),
            event_reader=lambda *a: self.fail("Must skip published"))
        self.assertEqual(counts["new_dossiers"], 0)
        first, _ = self.build([clue()])
        again, counts = build_backlog_dossiers(
            [clue()], first, self.catalogue, TODAY, self.key,
            agenda_reader=lambda *a: self.fail("Must skip queued"),
            event_reader=lambda *a: self.fail("Must skip queued"))
        self.assertEqual(counts["new_dossiers"], 0)
        self.assertEqual(len(again["open_world_research"]), 1)

    def test_resolved_history_does_not_consume_active_read_budget(self):
        # Many exact published occurrences and a pending dossier coexist
        # with fresh clues. The entire network budget remains useful.
        published = deepcopy(self.catalogue)
        historical = [clue(uid=810000 + i) for i in range(60)]
        for row in historical:
            published["events"].append({
                "id": "openagenda-" + row["external_id"] + "-" + DAY.isoformat()
            })
        prior, _ = self.build([clue()])
        fresh = [clue(uid=820000 + i) for i in range(MAX_ATTEMPTS)]
        rows = [*historical, clue(), *fresh]
        original = deepcopy(rows)
        seen = []
        def read_event(agenda_uid, uid, key):
            seen.append(uid)
            return dict(oa_event(), uid=uid)
        result, counts = build_backlog_dossiers(
            rows, prior, published, TODAY, self.key,
            agenda_reader=lambda *_: AGENDA, event_reader=read_event)
        self.assertEqual(counts["backlog_candidates"], 85)
        self.assertEqual(counts["backlog_candidates_already_published"], 60)
        self.assertEqual(counts["backlog_candidates_already_queued"], 1)
        self.assertEqual(counts["active_backlog_candidates"], MAX_ATTEMPTS)
        self.assertEqual(counts["live_events_read"], MAX_ATTEMPTS)
        self.assertEqual(set(seen), {int(row["external_id"]) for row in fresh})
        self.assertEqual(counts["new_dossiers"], MAX_ATTEMPTS)
        self.assertEqual(rows, original)
        self.assertEqual(result["additions"], [])
        self.assertFalse(result["safe_to_publish"])

    def test_publications_from_other_cycles_reclaim_full_queue_capacity(self):
        # A full private research queue may already have been published by
        # reconciliation or another cloud sync. Historical prompts remain
        # stored in the backlog but must not starve new first-party research.
        prior = []
        published = deepcopy(self.catalogue)
        for i in range(80):
            prior.append({
                "lead": {
                    "agenda_uid": AGENDA["uid"],
                    "agenda_slug": AGENDA["slug"],
                    "event_uid": 800000 + i,
                },
                "date_start": DAY.isoformat(),
                "official_event_url":
                    "https://openagenda.com/agenda-nouveau-organisateur/events/"
                    + str(800000 + i),
                "official_venue_url":
                    "https://openagenda.com/agenda-nouveau-organisateur/events/"
                    + str(800000 + i),
            })
            published["events"].append({
                "id": "openagenda-" + str(800000 + i) + "-" + DAY.isoformat()
            })
        patch = dict(self.patch, open_world_research=prior)
        result, counts = build_backlog_dossiers(
            [clue()], patch, published, TODAY, self.key,
            agenda_reader=lambda *_: AGENDA,
            event_reader=lambda *_: oa_event())
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertEqual(counts["queued_total"], 1)
        self.assertEqual(result["open_world_research"][0]["lead"]["event_uid"],
                         999401)
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(result["additions"], [])

    def test_expired_queue_is_replaced_by_live_future_research(self):
        stale = dict(
            self.build([clue()])[0]["open_world_research"][0],
            date_start=(TODAY-timedelta(days=1)).isoformat(),
        )
        patch = dict(self.patch, open_world_research=[stale])
        result, counts = build_backlog_dossiers(
            [clue()], patch, self.catalogue, TODAY, self.key,
            agenda_reader=lambda *_: AGENDA,
            event_reader=lambda *_: oa_event())
        self.assertEqual(counts["queued_total"], 1)
        self.assertEqual(result["open_world_research"][0]["date_start"],
                         DAY.isoformat())

    def test_full_80_from_one_source_cannot_starve_an_unlisted_agenda(self):
        # No venue/territory allowlist: a completely unknown OA agenda
        # is eligible for a live check even when the 80-place request queue
        # is already filled by one recurring series in another agenda.
        from datetime import date
        prior = []
        for day_offset in range(80):
            day = (TODAY + timedelta(days=day_offset)).isoformat()
            old_uid = 441100
            prior.append({
                "lead": {
                    "agenda_uid": 20001,
                    "agenda_slug": "high-volume-calendar",
                    "event_uid": old_uid,
                    "title": TITLE,
                    "city_unverified": "Ville artistique",
                    "venue_unverified": "Studio",
                },
                "date_start": day,
                "official_event_url":
                    "https://openagenda.com/high-volume-calendar/events/441100",
                "official_venue_url":
                    "https://openagenda.com/high-volume-calendar/events/441100",
            })
        saturated = dict(self.patch, open_world_research=prior)
        calls = []
        def live_agenda(slug, key):
            calls.append(slug)
            return AGENDA
        result, counts = build_backlog_dossiers(
            [clue()], saturated, self.catalogue, TODAY, self.key,
            agenda_reader=live_agenda,
            event_reader=lambda *_: oa_event())
        self.assertEqual(len(result["open_world_research"]), 80)
        self.assertEqual(counts["new_dossiers"], 1)
        self.assertIn(AGENDA["slug"], calls)
        # Eight bounded source rechecks may precede backlog admission.
        self.assertLessEqual(len(calls), 9)
        self.assertEqual(
            len([x for x in result["open_world_research"]
                 if x["lead"]["event_uid"] == 999401]), 1)
        self.assertGreater(counts["reviewed_not_selected_this_cycle"], 0)
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(result["additions"], [])

    def test_full_queue_without_valid_live_backlog_is_preserved(self):
        prior = [{
            "lead": {
                "agenda_uid": 20001, "agenda_slug": "a-new-calendar",
                "event_uid": 11100 + i,
            },
            "date_start": DAY.isoformat(),
            "official_event_url": "https://openagenda.com/a-new-calendar/events/11100",
            "official_venue_url": "https://openagenda.com/a-new-calendar/events/11100",
        } for i in range(80)]
        old_patch = dict(self.patch, open_world_research=prior)
        result, counts = build_backlog_dossiers(
            [clue()], old_patch, self.catalogue, TODAY, self.key,
            agenda_reader=lambda *args: AGENDA,
            event_reader=lambda *_: dict(oa_event(), uid=999402))
        self.assertEqual(result["open_world_research"], prior)
        self.assertEqual(counts["new_dossiers"], 0)
        self.assertEqual(counts["held_for_publisher_or_network"], 1)

    def test_live_confirmed_commercial_series_reclaims_real_queue_capacity(self):
        """One high-volume commercial UID must not crowd out new agendas."""
        from test_ptitesondes_oa_evergreen_on_demand import studio_bookings
        old_uid = 777001
        prior = []
        for i in range(45):
            prior.append({
                "lead": {
                    "agenda_uid": 20001, "agenda_slug": "commercial-calendar",
                    "event_uid": old_uid,
                },
                "date_start": (DAY + timedelta(days=i)).isoformat(),
                "official_event_url":
                    "https://openagenda.com/commercial-calendar/events/777001",
                "official_venue_url":
                    "https://openagenda.com/commercial-calendar/events/777001",
            })
        for i in range(35):
            uid = 780000 + i
            prior.append({
                "lead": {
                    "agenda_uid": 20001, "agenda_slug": "commercial-calendar",
                    "event_uid": uid,
                },
                "date_start": DAY.isoformat(),
                "official_event_url":
                    "https://openagenda.com/commercial-calendar/events/" + str(uid),
                "official_venue_url":
                    "https://openagenda.com/commercial-calendar/events/" + str(uid),
            })
        patch = dict(self.patch, open_world_research=prior)
        def agenda_reader(slug, _key):
            return ({"uid": 20001, "slug": "commercial-calendar"}
                    if slug == "commercial-calendar" else AGENDA)
        def event_reader(_agenda_uid, uid, _key):
            return (dict(studio_bookings(), uid=uid) if uid == old_uid
                    else dict(oa_event(), uid=uid))
        result, metrics = build_backlog_dossiers(
            [clue()], patch, self.catalogue, TODAY, self.key,
            agenda_reader=agenda_reader, event_reader=event_reader)
        self.assertEqual(metrics["live_confirmed_commercial_slots_reclaimed"], 45)
        self.assertEqual(metrics["new_dossiers"], 1)
        self.assertEqual(len(result["open_world_research"]), 36)
        self.assertFalse(any(x["lead"]["event_uid"] == old_uid
                             for x in result["open_world_research"]))
        self.assertTrue(any(x["lead"]["event_uid"] == 999401
                            for x in result["open_world_research"]))
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(result["additions"], [])

    def test_unavailable_or_real_musical_series_is_never_pruned(self):
        from test_ptitesondes_oa_evergreen_on_demand import long_days
        row = {
            "lead": {
                "agenda_uid": 20001, "agenda_slug": "family-calendar",
                "event_uid": 777002,
            },
            "date_start": DAY.isoformat(),
            "official_event_url": "https://openagenda.com/family-calendar/events/777002",
            "official_venue_url": "https://openagenda.com/family-calendar/events/777002",
        }
        repeated = [dict(row, date_start=(DAY + timedelta(days=i)).isoformat())
                    for i in range(50)]
        agenda = lambda *_: {"uid": 20001, "slug": "family-calendar"}
        real = dict(oa_event(), uid=777002,
                    title={"fr": "Conte musical jeunesse"},
                    description={"fr": "Spectacle musical pour enfants."},
                    conditions={"fr": "Sur réservation."},
                    timings=long_days())
        for reader in (lambda *_: real,
                       lambda *_: (_ for _ in ()).throw(OSError("unavailable"))):
            with self.subTest(reader=reader):
                remaining, reclaimed = reclaim_live_confirmed_on_demand(
                    repeated, self.key, agenda, reader)
                self.assertEqual(remaining, repeated)
                self.assertEqual(reclaimed, 0)

    def test_four_daily_slots_rotate_up_to_eighty_private_dossiers(self):
        # Existing 345+ future clues exceed 30/day. Four independently
        # selected same-day slots must not starve behind a queue of 30,
        # but the public Publisher still rechecks every untrusted record.
        rows = [clue(uid=800000 + i) for i in range(120)]
        def event(agenda_uid, uid, key):
            return dict(oa_event(), uid=uid)
        current = self.patch
        expected_new = (24, 24, 24, 8)
        expected_total = (24, 48, 72, 80)
        for slot in range(4):
            current, metrics = build_backlog_dossiers(
                rows, current, self.catalogue, TODAY, self.key,
                batch_index=slot,
                agenda_reader=lambda *_: AGENDA,
                event_reader=event)
            self.assertEqual(metrics["new_dossiers"], expected_new[slot])
            self.assertEqual(len(current["open_world_research"]), expected_total[slot])
            self.assertFalse(current["safe_to_publish"])
            self.assertEqual(current["additions"], [])
        uids = [x["lead"]["event_uid"] for x in current["open_world_research"]]
        self.assertEqual(len(set(uids)), 80)
        self.assertEqual(len(uids), 80)

    def test_bounded_rotation_across_unnamed_sources(self):
        rows = [clue(uid=800000+i) for i in range(48)]
        def event(agenda_uid, uid, key):
            return dict(oa_event(), uid=uid)
        def published_none():
            return self.catalogue
        first, c0 = self.build(rows, batch_index=0, event_reader=event)
        second, c1 = self.build(rows, batch_index=1, event_reader=event)
        self.assertEqual(c0["new_dossiers"], MAX_ATTEMPTS)
        self.assertEqual(c1["new_dossiers"], MAX_ATTEMPTS)
        ids0 = {x["lead"]["event_uid"] for x in first["open_world_research"]}
        ids1 = {x["lead"]["event_uid"] for x in second["open_world_research"]}
        self.assertFalse(ids0 & ids1)
        self.assertFalse(first["safe_to_publish"])


    def test_imminent_unlisted_session_is_reviewed_before_distant_backlog(self):
        # The deadline lane is general: no source/venue/territory/UID exception.
        # Hundreds of unrelated later events must not make a real family
        # performance expire before the Publisher ever examines its UID.
        soon = ("previously-unlisted-agenda", 990001,
                (TODAY + timedelta(days=2)).isoformat(), "Contes jeunesse")
        later = [("new-agenda-" + str(i), 910000 + i,
                  (TODAY + timedelta(days=30)).isoformat(), "Atelier musical")
                 for i in range(500)]
        ordered = fair_backlog_identity_order(set([soon, *later]))
        selected = deadline_aware_backlog_batch(ordered, TODAY, 0)
        self.assertEqual(len(selected), MAX_ATTEMPTS)
        self.assertEqual(len(set(selected)), MAX_ATTEMPTS)
        self.assertIn(soon, selected)
        self.assertLessEqual(
            sum(row[2] <= (TODAY + timedelta(days=3)).isoformat()
                for row in selected), 8)

    def test_four_slots_cover_all_near_term_events_without_a_closed_list(self):
        # A 28-event near-term backlog rotates completely within four daily
        # checks even with 500 far-future leads. No named city is privileged.
        imminent = [
            ("unlisted-agenda-" + str(i), 900000 + i,
             (TODAY + timedelta(days=2)).isoformat(), "Conte")
            for i in range(28)
        ]
        distant = [
            ("a-new-source-" + str(i), 800000 + i,
             (TODAY + timedelta(days=35)).isoformat(), "Concert")
            for i in range(500)
        ]
        ordered = fair_backlog_identity_order(set([*imminent, *distant]))
        batches = [deadline_aware_backlog_batch(ordered, TODAY, slot)
                   for slot in range(4)]
        reached = {row for batch in batches for row in batch}
        self.assertTrue(set(imminent).issubset(reached))
        self.assertTrue(all(len(batch) == MAX_ATTEMPTS for batch in batches))
        self.assertTrue(all(len(set(batch)) == MAX_ATTEMPTS
                            for batch in batches))

    def test_without_urgent_sessions_preserves_existing_rotation(self):
        later = [
            ("unlisted-organizer-" + str(i), 700000 + i,
             (TODAY + timedelta(days=50)).isoformat(), "Youth concert")
            for i in range(101)
        ]
        ordered = fair_backlog_identity_order(set(later))
        for slot in range(4):
            start = ((TODAY.toordinal() * 4 + slot)
                     * MAX_ATTEMPTS % len(ordered))
            expected = [ordered[(start + i) % len(ordered)]
                        for i in range(MAX_ATTEMPTS)]
            self.assertEqual(
                deadline_aware_backlog_batch(ordered, TODAY, slot), expected)

    def test_no_false_approval_or_network_dependency_from_priority_lane(self):
        near = [clue(uid=900000 + i,
                     day=(TODAY + timedelta(days=2)).isoformat())
                for i in range(12)]
        distant = [clue(uid=800000 + i,
                        day=(TODAY + timedelta(days=40)).isoformat())
                   for i in range(60)]
        fetched = []
        def fake_event(agenda_uid, uid, key):
            fetched.append(uid)
            # Wrong date is never silently repaired or authorized.
            return dict(oa_event(), uid=uid)
        result, counts = self.build(
            [*near, *distant], event_reader=fake_event)
        self.assertEqual(counts["clues_examined"], MAX_ATTEMPTS)
        self.assertEqual(counts["new_dossiers"], 0)
        self.assertEqual(result["additions"], [])
        self.assertFalse(result["safe_to_publish"])
        self.assertEqual(counts["queued_total"], 0)


if __name__ == "__main__":
    unittest.main()


class EditorialPolicyReconsiderationTests(unittest.TestCase):
    def test_policy_change_revokes_refusal_but_preserves_recheck_priority(self):
        from ptitesondes_editorial_refusal_memory import empty_memory, fresh_memory, identity_key
        from ptitesondes_openagenda_backlog_private_dossiers import persistent_backlog_batch
        now = datetime(2026, 11, 26, 10, tzinfo=timezone.utc)
        identities = [("agenda", n, "2026-12-10", "Conte") for n in range(1, 61)]
        old = empty_memory()
        old["policy"] = "0"*64
        target = identity_key(identities[-1])
        old["entries"][target] = dict(reason="oa_direct_out_of_editorial_scope",
            checked_at=now.isoformat(), clue_sha256="a"*64, source_sha256="b"*64)
        memory = fresh_memory(old, now)
        self.assertEqual(memory["entries"], {})
        self.assertEqual(memory["reconsider"], [target])
        self.assertEqual(fresh_memory(memory, now)["reconsider"], [target])
        chosen = persistent_backlog_batch(identities, now.date(), memory,
                                          {row: "a"*64 for row in identities})
        self.assertIn(identities[-1], chosen)
        self.assertEqual(len(chosen), MAX_ATTEMPTS)

    def test_priority_reserves_capacity_for_urgent_and_ordinary_candidates(self):
        from ptitesondes_editorial_refusal_memory import empty_memory, identity_key
        from ptitesondes_openagenda_backlog_private_dossiers import persistent_backlog_batch
        today = TODAY
        urgent = [("a", n, today.isoformat(), "Conte") for n in range(1, 21)]
        ordinary = [("b", n, (today+timedelta(days=10)).isoformat(), "Conte")
                    for n in range(1, 41)]
        memory = empty_memory()
        memory["reconsider"] = [identity_key(row) for row in ordinary[20:]]
        chosen = persistent_backlog_batch(urgent+ordinary, today, memory,
            {row: "a"*64 for row in urgent+ordinary})
        self.assertEqual(len(chosen), MAX_ATTEMPTS)
        self.assertEqual(sum(row in urgent for row in chosen), 8)
        self.assertEqual(sum(row in ordinary[:20] for row in chosen), 8)
        self.assertEqual(sum(row in ordinary[20:] for row in chosen), 8)
