"""Offline regression contract for published OpenAgenda series drift watch."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_published_oa_drift_watch import (
    index_published, choose_groups, compare_official_source, watch)


TODAY = date(2026, 11, 22)


def published(uid=111, day="2026-12-05", time="10:00", venue="Salle ouverte",
              slug="musique-jeunesse", agenda="agenda-generique"):
    return {"id": f"openagenda-{uid}-{day}", "date_start": day,
            "date_end": day, "title": "Atelier musical pour enfants",
            "category": "atelier-musical", "time": time,
            "source_url": f"https://openagenda.com/{agenda}/events/{uid}_{slug}",
            "venue": venue, "city": "Brest", "lat": 48.4, "lng": -4.5}


def source(uid=111, day="2026-12-05", time="10:00", venue="Salle ouverte",
           slug="musique-jeunesse", status=1):
    return {"uid": uid, "slug": slug, "state": 2, "status": status,
            "removed": False, "timezone": "Europe/Paris",
            "timings": [
                {"begin": f"{day}T{time}:00+01:00",
                 "end": f"{day}T12:00:00+01:00"}],
            "location": {"name": venue, "adminLevel4": "Brest",
                         "latitude": 48.4, "longitude": -4.5}}


class PublishedDriftWatchTests(unittest.TestCase):
    def test_nominal_source_does_not_report_false_positive(self):
        group = index_published({"events": [published()]}, TODAY)
        self.assertEqual(len(group), 1)
        self.assertEqual(compare_official_source(
            source(), next(iter(group.values())), TODAY), [])

    def test_cancelled_and_rescheduled_are_detected_from_uid_bound_source(self):
        g = next(iter(index_published({"events": [published()]}, TODAY).values()))
        changed = source(status=6)
        self.assertEqual(compare_official_source(
            changed, g, TODAY), ["cancelled_or_removed"])
        changed = source(day="2026-12-07", status=2)
        self.assertIn("source_session_missing",
                      compare_official_source(changed, g, TODAY))
        self.assertIn("source_new_future_session",
                      compare_official_source(changed, g, TODAY))

    def test_openagenda_distinguishes_cancelled_postponed_and_sold_out(self):
        group = next(iter(index_published(
            {"events": [published()]}, TODAY).values()))
        for number, expected in (
            (3, ["source_moved_online"]),
            (4, ["source_postponed"]),
            (5, ["source_sold_out"]),
            (6, ["cancelled_or_removed"]),
        ):
            with self.subTest(status=number):
                self.assertEqual(compare_official_source(
                    source(status=number), group, TODAY), expected)
        unpublished = source()
        unpublished["state"] = 0
        self.assertEqual(compare_official_source(
            unpublished, group, TODAY), ["source_unpublished"])

    def test_timezone_offset_is_checked_against_actual_venue_zone(self):
        group = next(iter(index_published(
            {"events": [published()]}, TODAY).values()))
        bad = source()
        bad["timings"][0]["begin"] = "2026-12-05T10:00:00+02:00"
        self.assertEqual(compare_official_source(
            bad, group, TODAY), ["unusable_source_timings"])
        bad = source()
        bad["timezone"] = "Pacific/Kiritimati"
        self.assertEqual(compare_official_source(
            bad, group, TODAY), ["unusable_source_timings"])

    def test_a_malformed_or_ambiguous_session_cannot_infer_cancellation(self):
        group = next(iter(index_published(
            {"events": [published()]}, TODAY).values()))
        for bad_timing in (
            {"begin": "not-a-date", "end": "2026-12-05T12:00:00+01:00"},
            {"begin": "2026-12-05T10:00:00+01:00"},
            {"begin": "2026-12-05T10:00:00+01:00",
             "end": "2026-12-07T12:00:00+01:00"},
        ):
            invalid = source()
            invalid["timings"].append(bad_timing)
            with self.subTest(timing=bad_timing):
                self.assertEqual(compare_official_source(
                    invalid, group, TODAY), ["unusable_source_timings"])

    def test_overseas_local_timezone_is_not_interpreted_as_paris(self):
        event = published()
        event["time"] = "10:00"
        group = next(iter(index_published(
            {"events": [event]}, TODAY).values()))
        observed = source()
        observed["timezone"] = "America/Martinique"
        observed["timings"] = [{
            "begin": "2026-12-05T10:00:00-04:00",
            "end": "2026-12-05T11:00:00-04:00",
        }]
        self.assertEqual(compare_official_source(
            observed, group, TODAY), [])

    def test_precise_showtime_and_venue_changes_are_detected(self):
        g = next(iter(index_published({"events": [published()]}, TODAY).values()))
        changed = source(time="11:00", venue="Nouvelle salle")
        changed["location"]["latitude"] = 48.41
        changed["location"]["adminLevel4"] = "Quimper"
        issues = compare_official_source(changed, g, TODAY)
        self.assertEqual(issues, [
            "city_changed", "source_session_time_changed",
            "venue_coordinates_changed", "venue_name_changed"])

    def test_network_failure_is_unavailable_not_cancelled(self):
        group = index_published({"events": [published()]}, TODAY)
        def missing(uid, key, slug):
            raise TimeoutError("simulated outage")
        report = watch({"events": [published()]}, TODAY, "read-only-test", 0,
                       read_event=missing)
        self.assertEqual(report["reason_counts"], {"source_unavailable": 1})
        self.assertNotIn("cancelled_or_removed", report["reason_counts"])
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["catalogue_modified"])
        self.assertEqual(len(group), report["total_source_series"])

    def test_changed_source_uid_or_slug_cannot_approve_cancellation(self):
        g = next(iter(index_published({"events": [published()]}, TODAY).values()))
        for bad in (source(uid=222), source(slug="different")):
            self.assertEqual(compare_official_source(
                bad, g, TODAY), ["source_identity_changed"])

    def test_one_event_with_thirty_seven_sessions_is_one_source_query(self):
        days = [f"2026-12-{d:02d}" for d in range(1, 31)]
        days += [f"2027-01-{d:02d}" for d in range(1, 8)]
        items = [published(day=day) for day in days]
        observed = source(day=days[0])
        observed["timings"] = [
            {"begin": f"{day}T10:00:00+01:00",
             "end": f"{day}T11:00:00+01:00"}
            for day in days]
        calls = []
        def read(uid, key, slug):
            calls.append(uid)
            return observed
        result = watch({"events": items}, TODAY, "read-only-test", 2,
                       read_event=read)
        self.assertEqual(calls, [111])
        self.assertEqual(result["source_series_checked"], 1)
        self.assertEqual(result["reason_counts"], {})

    def test_rotation_is_generic_disjoint_and_exhaustive(self):
        entries = {("agenda-"+str(i), i): {"published": [], "slug":"x"}
                   for i in range(121)}
        coverage = set()
        for offset in range(4):
            checked = choose_groups(entries, TODAY, offset)
            self.assertEqual(len(checked), 30)
            self.assertTrue(coverage.isdisjoint(checked))
            coverage.update(checked)
        self.assertEqual(len(coverage), 120)
        # Every source eventually gets checked by consecutive future batches.
        additional = choose_groups(entries, TODAY + timedelta(days=1), 0)
        self.assertEqual(len(additional), 30)
        self.assertTrue(set(additional) & set(entries))

    def test_unrelated_legacy_source_excluded_from_openagenda_drift(self):
        old = published()
        old["id"] = "historical-other-source"
        old["source_url"] = "https://ville.example/atelier"
        self.assertEqual(index_published({"events": [old]}, TODAY), {})

    def test_malformed_source_does_not_mutate_catalogue(self):
        orig = {"events": [published()]}
        before = repr(orig)
        report = watch(orig, TODAY, "read-only-test", 0,
                       read_event=lambda *args: {"uid":999})
        self.assertEqual(report["reason_counts"],
                         {"source_identity_changed":1})
        self.assertEqual(before, repr(orig))


if __name__ == "__main__":
    unittest.main()
