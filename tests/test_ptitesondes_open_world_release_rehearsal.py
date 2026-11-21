"""Offline end-to-end rehearsal of an unknown young-public musical event.

No known city, venue, source domain or organizer list. Show that actual
factory-minted independent geography, DILA municipality authentication, exact
fresh OA timings and etalab attribution can be sufficient for a candidate
REHEARSAL while the production publisher stays unchanged.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_unnumbered_official_geo_proof import (
    mint, directory, CITY, VENUE, POINT,
)
from test_ptitesondes_candidate_promotion import base
from ptitesondes_open_world_release_rehearsal import (
    rehearse_open_world_municipal_event,
)

TODAY = date(2026, 11, 21)
DAY = date(2026, 12, 5)
KEY = "oa_pk_open_world_release_rehearsal_test"
TITLE = "Conte musical pour enfants"
SOURCE = "https://www.ville-les-bois.fr/agenda/conte-musical"
AGENDA = {"uid": 809913, "slug": "agenda-nouveau-organisateur"}


def sessions(hours=(10, 15)):
    result = []
    for hour in hours:
        start = datetime(2026, 12, 5, hour,
                         tzinfo=timezone(timedelta(hours=1)))
        result.append({"begin": start.isoformat(timespec="seconds"),
                       "end": (start+timedelta(minutes=40))
                         .isoformat(timespec="seconds")})
    return result


def lead(hours=(10, 15)):
    return {
        "agenda_uid": AGENDA["uid"], "agenda_slug": AGENDA["slug"],
        "event_uid": 999401, "title": TITLE, "city_unverified": CITY,
        "venue_unverified": VENUE,
        "explicit_source_session_intervals": sessions(hours),
        "publication_ready": False, "public_writes": 0,
    }


def oa_event(hours=(10, 15)):
    return {
        "uid": 999401, "slug": "conte-musical",
        "state": 2, "status": 1, "removed": False,
        "attendanceMode": 1, "timezone": "Europe/Paris",
        "title": {"fr": TITLE},
        "description": {"fr": "Conte musical pour enfants et familles"},
        "timings": sessions(hours),
        "age": {"min": 2, "max": 10},
        "updatedAt": "2026-11-20T19:00:00+01:00",
        "rights": {
            "license": {"id": "etalab-2.0"},
            "licensor": {"name": "Association musique des bois"},
            "publisher": {"name": "Grand agenda national"},
        },
        "location": {
            "name": VENUE, "adminLevel4": CITY,
            "adminLevel2": "Aveyron", "adminLevel1": "Occitanie",
            "countryCode": "FR", "latitude": POINT[0],
            "longitude": POINT[1],
        },
    }


def official_page(hours=(10, 15), *, school_only=False):
    clock = " et ".join(f"{h:02d}:00" for h in hours)
    audience = "Scolaires uniquement" if school_only else "Jeune public"
    return ("<html><head><title>" + TITLE + " — Agenda Ville-les-Bois</title>"
            "</head><body><h1>" + TITLE + "</h1>"
            "<article>5 décembre 2026 à " + clock +
            ", " + audience + ", " + VENUE + ", " + CITY +
            ".</article></body></html>")


def check(item=None, source=None, proof=None, published=None,
          page=None, dila=None):
    item = item or lead()
    source = source or oa_event()
    original = base()
    published = original if published is None else published
    return rehearse_open_world_municipal_event(
        item, DAY.isoformat(), SOURCE, mint() if proof is None else proof,
        original, published, TODAY, KEY,
        agenda_reader=lambda uid, key: AGENDA,
        event_reader=lambda uid, eid, key: source,
        directory_reader=lambda city: directory() if dila is None else dila,
        municipal_reader=lambda url: (
            official_page() if page is None else page),
    )


class RehearsalTests(unittest.TestCase):
    def test_new_unknown_musical_venue_and_domain_can_pass_private_rehearsal(self):
        review = check()
        self.assertTrue(review["private_rehearsal_positive"])
        e = review["candidate"]
        self.assertEqual(e["id"], "openagenda-999401-2026-12-05")
        self.assertEqual(e["time"], "10:00 ; 15:00")
        self.assertEqual(e["venue"], VENUE)
        self.assertEqual((e["lat"], e["lng"]), POINT)
        self.assertEqual(e["source_url"], SOURCE)
        self.assertIn("Association musique des bois", e["source_label"])
        self.assertIn("20/11/2026", e["source_label"])
        self.assertIn("Licence Ouverte 2.0", e["source_label"])
        self.assertNotIn("Grand agenda national", e["source_label"])
        self.assertTrue(review["published_duplicate_checked"])
        self.assertFalse(review["publication_ready"])
        self.assertFalse(review["publisher_connected"])
        self.assertEqual(review["public_writes"], 0)

    def test_more_than_four_real_same_day_sessions_all_kept(self):
        many = (9, 10, 11, 12, 13, 14, 15, 16)
        result = rehearse_open_world_municipal_event(
            lead(many), DAY.isoformat(), SOURCE, mint(),
            base(), base(), TODAY, KEY,
            agenda_reader=lambda uid, key: AGENDA,
            event_reader=lambda uid, eid, key: oa_event(many),
            directory_reader=lambda city: directory(),
            municipal_reader=lambda url: official_page(many))
        self.assertTrue(result["private_rehearsal_positive"])
        self.assertEqual(result["municipal_program_exact_sessions"], len(many))
        self.assertEqual(len(result["candidate"]["time"].split(";")), len(many))

    def test_forged_geometry_and_unsupported_sources_remain_held(self):
        forged = {"city": CITY, "venue": VENUE,
                  "lat": POINT[0], "lng": POINT[1], "approved": True}
        self.assertIsNone(check(proof=forged)["candidate"])
        self.assertEqual(check(dila={"results": []})["status"],
                         "unknown_municipal_official_source")

    def test_oa_changed_time_cancellation_or_bad_license_never_passes(self):
        for changed in (
            {"timings": sessions((11, 15))},
            {"status": 3},
            {"rights": {"license": {"id": "copyright"},
                        "licensor": {"name": "Association"}}},
            {"location": {**oa_event()["location"],
                          "latitude": 46.1}},
            {"title": {"fr": "Autre spectacle"}},
        ):
            with self.subTest(changed=changed):
                source = dict(oa_event(), **changed)
                self.assertFalse(check(source=source)[
                    "private_rehearsal_positive"])

    def test_unrelated_adult_private_page_is_not_public_family_proof(self):
        result = check(page=official_page(school_only=True))
        self.assertFalse(result["private_rehearsal_positive"])
        self.assertIsNone(result["candidate"])

    def test_missing_one_visible_hour_does_not_infer_schedule(self):
        result = check(page=official_page((10,)))
        self.assertFalse(result["private_rehearsal_positive"])

    def test_existing_single_card_or_date_range_is_never_duplicated(self):
        for duplicate in (
            {"id": "openagenda-999401-2026-12-05", "title": TITLE},
            {"id": "another-known-id", "title": TITLE,
             "date_start": "2026-12-04", "date_end": "2026-12-06"},
        ):
            current = base()
            known = dict(current["events"][0])
            known.update(duplicate)
            known["city"], known["venue"] = CITY, VENUE
            current["events"].append(known)
            result = check(published=current)
            self.assertFalse(result["private_rehearsal_positive"])

    def test_live_source_and_dila_network_readers_are_called_once(self):
        agenda_reader, event_reader = Mock(return_value=AGENDA), Mock(return_value=oa_event())
        municipal_reader, dila_reader = Mock(return_value=official_page()), Mock(return_value=directory())
        out = rehearse_open_world_municipal_event(
            lead(), DAY.isoformat(), SOURCE, mint(), base(), base(), TODAY,
            KEY, agenda_reader=agenda_reader, event_reader=event_reader,
            directory_reader=dila_reader, municipal_reader=municipal_reader)
        self.assertTrue(out["private_rehearsal_positive"])
        agenda_reader.assert_called_once()
        event_reader.assert_called_once()
        dila_reader.assert_called_once()
        municipal_reader.assert_called_once_with(SOURCE)


if __name__ == "__main__":
    unittest.main()
