"""Offline safety contract for automated first-party OA corrections and withdrawals."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from ptitesondes_official_reconciliation import reconcile as reconcile_live, digest, unwrap_exact_public_v2_event, assert_live_source_health
from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_published_oa_drift_watch import source

TODAY = date(2026, 11, 23)
DAY = "2026-12-05"
SRC = "https://openagenda.com/agenda-generique/events/111_musique-jeunesse"


def reconcile(catalogue, today, slot, **kwargs):
    kwargs.setdefault("as_of_utc", datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    return reconcile_live(catalogue, today, slot, **kwargs)


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
    def test_official_direct_v2_exact_uid_envelope_and_raw_event(self):
        v = live()
        self.assertEqual(unwrap_exact_public_v2_event(v, 111), v)
        self.assertEqual(unwrap_exact_public_v2_event({"event": v}, 111), v)
        for invalid in (
            {"event": dict(v, uid=999)},
            {"uid": 999, "event": v},
            {"uid": 111, "event": v},
            {"events": [v]},
            {"event": {"event": v}},
            {},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    ValueError, "official_v2"):
                    unwrap_exact_public_v2_event(invalid, 111)

    def test_all_sources_mismatch_must_fail_instead_of_green_noop(self):
        for code in ("official_identity_mismatch", "official_unavailable"):
            with self.subTest(code=code):
                with self.assertRaisesRegex(
                        RuntimeError, "all_first_party_oa_reads_failed"):
                    assert_live_source_health({
                        "source_series_checked": 27,
                        "source_summary": {code: 27},
                    })
        assert_live_source_health({
            "source_series_checked": 27,
            "source_summary": {
                "official_identity_mismatch": 3,
                "official_unchanged": 24,
            },
        })
        assert_live_source_health({
            "source_series_checked": 0, "source_summary": {},
        })

    def test_normalized_live_v2_envelope_passes_regular_reconciliation(self):
        wrapped = {"event": live(time="11:00", status=2)}
        ready = unwrap_exact_public_v2_event(wrapped, 111)
        result, audit, counts = check(document(row()), ready)
        self.assertEqual(counts["official_time_corrected"], 1)
        self.assertEqual(result["events"][0]["time"], "11:00")
        self.assertEqual(audit["operations"][0]["action"], "correct_time")

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

    def test_city_only_overseas_series_renews_exact_place_and_adds_missing_dates(self):
        """An official OA town centroid is not the already verified site."""
        old = row("2026-12-23")
        old.update({
            "id": "openagenda-111-2026-12-23",
            "city": "Basse-Pointe", "region": "Martinique",
            "department": "Martinique",
            "venue": "Centre Culturel Antoine Tangamen dit Zwazo",
            "lat": 14.86740401, "lng": -61.11625135,
            "time": "09:00",
        })
        official = live()
        official["timezone"] = "America/Martinique"
        official["location"] = {
            "name": "Basse-Pointe", "adminLevel4": "Basse-Pointe",
            "adminLevel1": "Martinique", "adminLevel2": "Martinique",
            "countryCode": "MQ",
            "latitude": 14.868227, "longitude": -61.113506,
        }
        official["timings"] = [{
            "begin": f"{day}T09:00:00-04:00",
            "end": f"{day}T11:00:00-04:00",
        } for day in ("2026-11-25", "2026-12-02", "2026-12-09",
                      "2026-12-16", "2026-12-23")]
        package = {"event": official,
                   "agenda": {"uid": 901131, "slug": "agenda-generique"}}
        proof = {"name": old["venue"],
                 "latitude": old["lat"], "longitude": old["lng"]}
        calls = []
        def resolve(source):
            calls.append(source["uid"])
            self.assertEqual(source["location"]["name"], "Basse-Pointe")
            return proof
        before = document(old)
        after, audit, counts = reconcile(
            before, TODAY, 0, read_event=lambda *_: package,
            resolve_city_venue=resolve)
        self.assertEqual(calls, [111])
        self.assertEqual(counts["official_new_session_admitted"], 1)
        self.assertEqual(len(after["events"]), 5)
        self.assertEqual(after["events"][0], old)
        self.assertEqual({x["date_start"] for x in after["events"][1:]},
                         {"2026-11-25", "2026-12-02", "2026-12-09", "2026-12-16"})
        self.assertTrue(all(x["venue"] == old["venue"] and
                            x["lat"] == old["lat"] and x["lng"] == old["lng"]
                            for x in after["events"]))
        self.assertEqual(sum(x["action"] == "add" for x in audit["operations"]), 4)
        self.assertEqual(before["events"], [old])
        # At 14:00 UTC the 09:00 Martinique session has already begun.
        late, late_audit, late_counts = reconcile(
            before, date(2026, 11, 25), 0, read_event=lambda *_: package,
            resolve_city_venue=resolve,
            as_of_utc=datetime(2026, 11, 25, 14, tzinfo=timezone.utc))
        self.assertEqual({x["date_start"] for x in late["events"]},
                         {"2026-12-02", "2026-12-09", "2026-12-16", "2026-12-23"})
        self.assertEqual(late["events"][0], old)
        self.assertEqual(sum(x["action"] == "add" for x in late_audit["operations"]), 3)
        self.assertEqual(late_counts["official_new_session_held"], 1)

    def test_city_only_reconciliation_rejects_missing_wrong_or_network_place(self):
        old = row()
        old.update({"venue": "Centre Culturel Antoine Tangamen dit Zwazo",
                    "lat": 14.86740401, "lng": -61.11625135,
                    "city": "Basse-Pointe", "region": "Martinique",
                    "department": "Martinique"})
        official = live()
        official["location"] = dict(
            official["location"], name="Basse-Pointe",
            adminLevel4="Basse-Pointe", adminLevel1="Martinique",
            adminLevel2="Martinique", countryCode="MQ",
            latitude=14.868227, longitude=-61.113506)
        official["timezone"] = "America/Martinique"
        official["timings"] = [{
            "begin": "2026-12-05T10:00:00-04:00",
            "end": "2026-12-05T12:00:00-04:00"}, {
            "begin": "2026-12-12T10:00:00-04:00",
            "end": "2026-12-12T12:00:00-04:00"}]
        envelope = {"event": official,
                    "agenda": {"uid": 901131, "slug": "agenda-generique"}}
        cases = [
            lambda *_: None,
            lambda *_: {"name": old["venue"],
                        "latitude": 14.868227, "longitude": -61.113506},
            lambda *_: (_ for _ in ()).throw(OSError("network offline")),
        ]
        for resolver in cases:
            with self.subTest(resolver=resolver):
                before = document(old)
                after, audit, counts = reconcile(
                    before, TODAY, 0, read_event=lambda *_: envelope,
                    resolve_city_venue=resolver)
                self.assertEqual(after, before)
                self.assertEqual(audit["operations"], [])
                self.assertEqual(counts["official_venue_gps_unconfirmed"], 1)

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

    def test_bookable_daily_studio_is_held_without_erasing_existing_sessions(self):
        """Paid, book-on-demand, mixed corporate studio calendar is NOT a
        confirmed set of daily child performances. Keep published row intact.
        """
        original = document(row())
        official = live()
        official["description"] = {
            "fr": "Atelier en studio professionnel et studio d'enregistrement"
        }
        official["longDescription"] = {
            "fr": "Enfants, team buildings, entreprises et particuliers"
        }
        official["conditions"] = {
            "fr": "Payant. Contactez-nous pour votre réservation"
        }
        official["timings"] = [
            {
                "begin": f"2026-12-{day:02d}T10:00:00+01:00",
                "end": f"2026-12-{day:02d}T12:00:00+01:00",
            }
            for day in range(5, 27)
        ]
        source_pkg = {
            "event": official,
            "agenda": {"uid": 901131, "slug": "agenda-generique"},
        }
        result, audit, reasons = check(original, source_pkg)
        self.assertEqual(result, original)
        self.assertEqual(audit["operations"], [])
        self.assertEqual(reasons["official_new_session_on_demand_review"], 1)
        self.assertNotIn("official_new_session_admitted", reasons)

    def test_no_session_cap_or_generic_reservation_blacklist(self):
        """A real 21-day series without corporate studio-service cues may
        publish its dates; legitimate reserved performances are allowed.
        """
        original = document(row())
        official = live()
        official["title"] = {"fr": "Atelier musical pour enfants"}
        official["description"] = {
            "fr": "Véritable atelier musical jeunesse à date et heure fixes."
        }
        official["conditions"] = {
            "fr": "Payant, sur réservation. Places limitées pour familles."
        }
        official["timings"] = [
            {
                "begin": f"2026-12-{day:02d}T10:00:00+01:00",
                "end": f"2026-12-{day:02d}T12:00:00+01:00",
            }
            for day in range(5, 26)
        ]
        after, audit, reasons = check(original, {
            "event": official,
            "agenda": {"uid": 901131, "slug": "agenda-generique"},
        })
        self.assertEqual(len(after["events"]), 21)
        self.assertEqual(sum(x["action"] == "add"
                             for x in audit["operations"]), 20)
        self.assertNotIn("official_new_session_on_demand_review", reasons)

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
