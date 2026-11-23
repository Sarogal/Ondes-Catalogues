"""Existing ODS/official OA backlog may request first-party UID verification."""
from copy import deepcopy
from datetime import timedelta
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
    build_backlog_dossiers, MAX_ATTEMPTS,
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


if __name__ == "__main__":
    unittest.main()
