"""Offline safety contract for automated first-party OA corrections and withdrawals."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from ptitesondes_official_reconciliation import reconcile, digest
from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_published_oa_drift_watch import source

TODAY = date(2026, 11, 23)
DAY = "2026-12-05"
SRC = "https://openagenda.com/agenda-generique/events/111_musique-jeunesse"


def row(day=DAY):
    e = deepcopy(base()["events"][0])
    e.update({
        "id": "openagenda-111-" + day,
        "title": "Atelier musical pour enfants",
        "category": "atelier-musical",
        "category_label": "Atelier musical",
        "date_start": day, "date_end": day,
        "time": "10:00", "city": "Brest",
        "department": "Finistère", "region": "Bretagne",
        "venue": "Salle ouverte", "source_url": SRC,
        "lat": 48.4, "lng": -4.5, "geo_precision": "venue",
        "verified_at": TODAY.isoformat(),
        "geo_verified_at": TODAY.isoformat(),
    })
    return e


def document(*events):
    return {
        "version": 3, "updated_at": "2026-11-23T04:00:00+01:00",
        "events": list(events) or [row()],
    }


def live(day=DAY, time="10:00", status=1):
    s = source(day=day, time=time, status=status)
    s["location"]["countryCode"] = "FR"
    s["location"]["adminLevel1"] = "Bretagne"
    s["location"]["adminLevel2"] = "Finistère"
    s["title"] = {"fr": "Atelier musical pour enfants"}
    s["description"] = {"fr": "Atelier musical pour enfants et familles."}
    s["age"] = {"min": 4, "max": 13}
    s["attendanceMode"] = 1
    s["updatedAt"] = "2026-11-22T12:00:00+01:00"
    s["rights"] = {
        "license": {"id": "etalab-2.0"},
        "licensor": {"name": "Organisateur culturel"},
        "publisher": {"name": "Agenda officiel"},
    }
    return s


def check(doc, event, *, day=TODAY):
    return reconcile(doc, day, 0, read_event=lambda uid, slug: event)


class OfficialReconciliationTests(unittest.TestCase):
    def test_real_source_cancellation_withdraws_only_exact_uid_and_future_days(self):
        other = dict(row(), id="historical-other-entry", source_url="https://ville.example/events/7")
        initial = document(row(), other)
        before = deepcopy(initial)
        after, audit, counts = check(initial, live(status=6))
        self.assertEqual(counts["cancelled_official"], 1)
        self.assertEqual(audit["before_count"], 2)
        self.assertEqual(audit["after_count"], 1)
        self.assertEqual(after["events"], [other])
        self.assertEqual(audit["operations"][0]["id"], row()["id"])
        self.assertEqual(audit["operations"][0]["action"], "withdraw")
        self.assertEqual(audit["catalogue_before_sha256"], digest(before))
        self.assertEqual(audit["catalogue_after_sha256"], digest(after))
        self.assertEqual(initial, before)

    def test_online_and_postponed_are_withdrawn_but_sold_out_is_not(self):
        for code in (3, 4):
            after, audit, counts = check(document(row()), live(status=code))
            self.assertEqual(len(after["events"]), 0)
            self.assertEqual(len(audit["operations"]), 1)
        after, audit, counts = check(document(row()), live(status=5))
        self.assertEqual(len(after["events"]), 1)
        self.assertEqual(audit["operations"], [])
        self.assertEqual(counts["official_sold_out_no_change"], 1)

    def test_first_party_clock_change_is_corrected_without_venue_or_title_change(self):
        old = row()
        initial = document(old)
        after, audit, counts = check(initial, live(time="11:00", status=2))
        self.assertEqual(counts["official_time_corrected"], 1)
        self.assertEqual(after["events"][0]["id"], old["id"])
        self.assertEqual(after["events"][0]["time"], "11:00")
        self.assertEqual(after["events"][0]["verified_at"], TODAY.isoformat())
        self.assertEqual(audit["operations"][0]["action"], "correct_time")
        self.assertEqual(initial["events"][0]["time"], "10:00")
        again, repeated_audit, _ = check(after, live(time="11:00", status=2))
        self.assertEqual(repeated_audit["operations"], [])
        self.assertEqual(again, after)

    def test_explicit_reschedule_with_future_new_date_removes_old_date_only(self):
        after, audit, counts = check(document(row()),
                                     live(day="2026-12-07", status=2))
        self.assertEqual(after["events"], [])
        self.assertEqual(counts["official_rescheduled_old_date_removed"], 1)
        self.assertEqual(audit["operations"][0]["reason"],
                         "official_rescheduled_old_date_removed")

    def test_non_rescheduled_missing_date_must_never_be_removed(self):
        before = document(row())
        after, audit, counts = check(before, live(day="2026-12-07", status=1))
        self.assertEqual(after, before)
        self.assertEqual(audit["operations"], [])
        self.assertEqual(counts["official_future_date_missing"], 1)

    def test_network_or_uid_conflict_does_not_modify_even_cancelled_source(self):
        before = document(row())
        def broken(uid, slug):
            raise TimeoutError("simulated official outage")
        after, audit, counts = reconcile(before, TODAY, 0, read_event=broken)
        self.assertEqual(after, before)
        self.assertEqual(counts["official_unavailable"], 1)
        mismatch = live(status=6)
        mismatch["uid"] = 2222
        after, audit, counts = check(before, mismatch)
        self.assertEqual(after, before)
        self.assertEqual(counts["official_identity_mismatch"], 1)

    def test_non_public_or_removed_is_a_hold_not_cancellation(self):
        before = document(row())
        for modified in ("state", "removed"):
            official = live(status=6)
            if modified == "state":
                official["state"] = 1
            else:
                official["removed"] = True
            after, audit, _ = check(before, official)
            self.assertEqual(after, before)
            self.assertEqual(audit["operations"], [])

    def test_venue_move_or_unknown_gps_never_edits_time(self):
        before = document(row())
        official = live(time="11:00", status=2)
        for change in ({"name": "Nouvelle salle"},
                       {"longitude": -4.7}, {"latitude": None}):
            altered = deepcopy(official)
            altered["location"].update(change)
            after, audit, counts = check(before, altered)
            self.assertEqual(after, before)
            self.assertEqual(audit["operations"], [])
            self.assertEqual(counts["official_venue_gps_unconfirmed"], 1)

    def test_missing_license_or_malformed_offset_never_edits(self):
        original = document(row())
        official = live(time="11:00")
        official["rights"]["license"]["id"] = "private"
        after, audit, counts = check(original, official)
        self.assertEqual(after, original)
        self.assertEqual(counts["official_rights_unconfirmed"], 1)
        official = live(time="11:00")
        official["timings"][0]["begin"] = "2026-12-05T11:00:00+02:00"
        after, audit, counts = check(original, official)
        self.assertEqual(after, original)
        self.assertEqual(counts["official_timings_invalid"], 1)

    def test_thirty_seven_sessions_in_one_program_without_session_ceiling(self):
        days = [f"2026-12-{day:02d}" for day in range(1, 32)]
        days += [f"2027-01-{day:02d}" for day in range(1, 7)]
        published = [row(day) for day in days]
        official = live(day=days[0], time="11:00", status=2)
        official["timings"] = [
            {"begin": day+"T11:00:00+01:00", "end": day+"T12:00:00+01:00"}
            for day in days
        ]
        calls = []
        def read(uid, slug):
            calls.append((uid, slug))
            return official
        after, audit, counts = reconcile(
            document(*published), TODAY, 0, read_event=read)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(after["events"]), 37)
        self.assertTrue(all(e["time"] == "11:00" for e in after["events"]))
        self.assertEqual(len(audit["operations"]), 37)

    def test_new_official_session_from_known_program_uses_full_live_publisher_gate(self):
        first = row()
        original = document(first)
        official = live()
        official["timings"].append({
            "begin": "2026-12-12T10:00:00+01:00",
            "end": "2026-12-12T12:00:00+01:00",
        })
        package = {
            "event": official,
            "agenda": {"uid": 901131, "slug": "agenda-generique"},
        }
        after, audit, counts = check(original, package)
        self.assertEqual(counts["official_new_session_admitted"], 1)
        self.assertEqual(len(after["events"]), 2)
        self.assertEqual(after["events"][0], first)
        self.assertEqual(after["events"][1]["id"], "openagenda-111-2026-12-12")
        self.assertEqual(after["events"][1]["time"], "10:00")
        self.assertEqual(after["events"][1]["category"], "atelier-musical")
        self.assertEqual(audit["operations"][0]["action"], "add")
        self.assertEqual(original["events"], [first])
        self.assertTrue(audit["unrelated_public_records_preserved"])
        again, repeated, _ = check(after, package)
        self.assertEqual(again, after)
        self.assertEqual(repeated["operations"], [])

    def test_forty_new_scheduled_sessions_are_not_artificially_capped(self):
        source_event = live()
        for number in range(6, 32):
            day = f"2026-12-{number:02d}"
            source_event["timings"].append({
                "begin": day+"T10:00:00+01:00",
                "end": day+"T12:00:00+01:00",
            })
        for number in range(1, 15):
            day = f"2027-01-{number:02d}"
            source_event["timings"].append({
                "begin": day+"T10:00:00+01:00",
                "end": day+"T12:00:00+01:00",
            })
        response = {
            "event": source_event,
            "agenda": {"uid": 901131, "slug": "agenda-generique"},
        }
        after, audit, counters = check(document(row()), response)
        self.assertEqual(len(after["events"]), 41)
        self.assertEqual(sum(x["action"] == "add" for x in audit["operations"]), 40)
        self.assertEqual(len({x["id"] for x in after["events"]}), 41)

    def test_cannot_self_approve_new_date_without_live_agenda_identity(self):
        original = document(row())
        official = live()
        official["timings"].append({
            "begin": "2026-12-12T10:00:00+01:00",
            "end": "2026-12-12T12:00:00+01:00",
        })
        for source in (
            official,  # event only: monitoring is not approval
            {"event": official, "agenda": {
                "uid": 901131, "slug": "wrong-agenda"}},
        ):
            after, audit, counts = check(original, source)
            self.assertEqual(after, original)
            self.assertEqual(audit["operations"], [])
            self.assertEqual(counts["official_new_session_agenda_unavailable"], 1)

    def test_new_date_must_still_confirm_child_audience_and_licensed_reuse(self):
        original = document(row())
        official = live()
        official["timings"].append({
            "begin": "2026-12-12T10:00:00+01:00",
            "end": "2026-12-12T12:00:00+01:00",
        })
        official["title"] = {"fr": "Atelier musical"}
        official["description"] = {"fr": "Pour les adultes"}
        official["age"] = None
        # Existing event has a different child title, so do not alter it.
        after, audit, counts = check(original, {
            "event": official, "agenda": {"uid": 901131,
                                         "slug": "agenda-generique"}})
        self.assertEqual(after, original)
        self.assertEqual(audit["operations"], [])

    def test_future_outside_publication_horizon_is_not_a_session_cap(self):
        official = live()
        far = (TODAY + timedelta(days=185)).isoformat()
        official["timings"].append({
            "begin": far+"T10:00:00+02:00",
            "end": far+"T12:00:00+02:00",
        })
        after, audit, counts = check(document(row()), {
            "event": official, "agenda": {"uid": 901131,
                                         "slug": "agenda-generique"}})
        self.assertEqual(len(after["events"]), 1)
        self.assertEqual(audit["operations"], [])

    def test_untrusted_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate_public_ids"):
            check(document(row(), row()), live(status=6))

    def test_old_occurences_are_out_of_scope_even_when_program_cancelled(self):
        old = row("2026-11-22")
        future = row("2026-12-05")
        after, audit, counts = check(document(old, future), live(status=6))
        self.assertEqual(after["events"], [old])
        self.assertEqual([x["id"] for x in audit["operations"]], [future["id"]])


if __name__ == "__main__":
    unittest.main()
