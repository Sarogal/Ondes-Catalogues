"""Exact local showtime hints must survive OPEN-WORLD research, never publish."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_openagenda_national_event_research import (
    _time_days, _time_sessions, _unclassified_source_research_hint, propose_event,
    MAX_TIMINGS,
)

DAY = date(2026, 11, 21)
AGENDA = {"agenda_uid": 712345, "agenda_slug": "agenda-inconnue"}


def row(title="Concert jeune public", timings=None, status=1):
    if timings is None:
        timings = [
            {"begin": f"2026-12-12T{hour:02d}:00:00+01:00",
             "end": f"2026-12-12T{hour:02d}:45:00+01:00"}
            for hour in range(9, 15)
        ]
    return {
        "uid": 98123, "title": {"fr": title},
        "description": {"fr": "Pour les enfants et familles"},
        "state": 2, "status": status, "removed": False,
        "location": {"name": "Place des enfants", "adminLevel4": "Ville nouvelle",
                     "countryCode": "FR"},
        "timings": timings,
    }


class ExactOpenAgendaLocalSessionsTests(unittest.TestCase):
    def test_six_same_day_shows_do_not_collapse_into_one_show(self):
        proposal, status = propose_event(row(), AGENDA, DAY)
        self.assertEqual(status, "editorial_candidate")
        self.assertEqual(proposal["explicit_source_session_days"], ["2026-12-12"])
        sessions = proposal["explicit_source_session_intervals"]
        self.assertEqual(len(sessions), 6)
        self.assertEqual(sessions[0]["begin"], "2026-12-12T09:00:00+01:00")
        self.assertEqual(sessions[-1]["end"], "2026-12-12T14:45:00+01:00")
        self.assertFalse(proposal["session_verified"])
        self.assertFalse(proposal["publication_ready"])
        self.assertEqual(proposal["public_writes"], 0)

    def test_fifty_shows_preserve_local_offset_and_order_in_overseas_territory(self):
        starts = []
        for day_offset in range(10):
            for hour in range(9, 14):
                start = datetime(2026, 12, 12 + day_offset, hour,
                                 tzinfo=timezone(timedelta(hours=4)))
                finish = start + timedelta(minutes=35)
                starts.append({"begin": start.isoformat(), "end": finish.isoformat()})
        sessions, reason = _time_sessions(list(reversed(starts)), DAY)
        self.assertEqual(reason, "explicit_future_intervals")
        self.assertEqual(len(sessions), 50)
        self.assertEqual(len(_time_days(starts, DAY)[0]), 10)
        self.assertEqual(sessions[0]["begin"], "2026-12-12T09:00:00+04:00")
        self.assertEqual(sessions[-1]["end"], "2026-12-21T13:35:00+04:00")
        self.assertTrue(all(x["begin"].endswith("+04:00") for x in sessions))

    def test_guadeloupe_negative_offset_and_overnight_end_remain_local(self):
        entries = [{"begin": "2026-12-12T23:30:00-04:00",
                    "end": "2026-12-13T00:20:00-04:00"},
                   {"begin": "2026-12-13T10:00:00-04:00",
                    "end": "2026-12-13T10:40:00-04:00"}]
        result, _ = propose_event(row(timings=entries), AGENDA, DAY)
        self.assertEqual(result["explicit_source_session_days"],
                         ["2026-12-12", "2026-12-13"])
        self.assertEqual(result["explicit_source_session_intervals"], entries)
        self.assertFalse(result["location_verified"])

    def test_research_only_unknown_artistic_form_keeps_exact_shows(self):
        unknown = row(title="Expérience narrative inédite")
        unknown["uid"] = 98124
        hint = _unclassified_source_research_hint(unknown, AGENDA, DAY)
        self.assertIsNone(hint["editorial_category_proposal"])
        self.assertEqual(len(hint["explicit_source_session_intervals"]), 6)
        self.assertFalse(hint["source_organizer_independently_verified"])
        self.assertFalse(hint["publisher_connected"])
        self.assertFalse(hint["publication_ready"])
        self.assertEqual(hint["public_writes"], 0)

    def test_malformed_naive_duplicate_and_past_intervals_are_not_invented(self):
        entries = [
            {"begin": "2026-12-12T09:00:00+01:00",
             "end": "2026-12-12T09:45:00+01:00"},
            {"begin": "2026-12-12T09:00:00+01:00",
             "end": "2026-12-12T09:45:00+01:00"},
            {"begin": "2026-12-12T10:00:00",
             "end": "2026-12-12T10:45:00"},
            {"begin": "2026-12-12T11:00:00+01:00",
             "end": "2026-12-12T10:45:00+01:00"},
            {"begin": "2026-11-20T09:00:00+01:00",
             "end": "2026-11-20T09:45:00+01:00"},
            {"begin": "2026-12-12T09:00:00+01:00"},
        ]
        sessions, reason = _time_sessions(entries, DAY)
        self.assertEqual(reason, "explicit_future_intervals")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["begin"], "2026-12-12T09:00:00+01:00")
        self.assertEqual(_time_days(entries, DAY)[0], ["2026-12-12"])

    def test_absurd_volume_does_not_create_fake_dates(self):
        sessions, reason = _time_sessions(
            [{"begin": "2026-12-12T09:00:00+01:00",
              "end": "2026-12-12T10:00:00+01:00"}]
            * (MAX_TIMINGS + 1), DAY)
        self.assertEqual(sessions, [])
        self.assertEqual(reason, "timings_invalid_or_too_many")

    def test_rescheduled_and_cancelled_never_become_verified(self):
        rescheduled, status = propose_event(row(status=2), AGENDA, DAY)
        self.assertEqual(status, "editorial_candidate")
        self.assertTrue(rescheduled["requires_reprogramming_verification"])
        self.assertEqual(len(rescheduled["explicit_source_session_intervals"]), 6)
        self.assertFalse(rescheduled["session_verified"])
        cancelled, status = propose_event(row(status=4), AGENDA, DAY)
        self.assertIsNone(cancelled)
        self.assertEqual(status, "cancelled_or_unconfirmed_event")


    def test_private_campaign_rejects_forged_session_hints(self):
        from ptitesondes_private_national_event_campaign import _validate_segment
        good = [{"begin": "2026-12-12T09:00:00+01:00",
                 "end": "2026-12-12T09:45:00+01:00"}]
        meta = {"source_sha256": "a" * 64, "scan_day": str(DAY),
                "agenda_index": 0, "segment": 0, "start_cursor": None}
        base = {
            "schema": "ptitesondes.private_oa_agenda_event_exploration.v1",
            "mode": "private_research_event_leads_only",
            "agenda_uid": AGENDA["agenda_uid"],
            "agenda_slug": AGENDA["agenda_slug"],
            "counts": {"pages_read": 1, "public_event_uids_seen": 1},
            "event_leads": [
                {"event_uid": 98123, "publication_ready": False,
                 "public_writes": 0,
                 "explicit_source_session_intervals": good}],
            "no_publisher_bridge": True, "next_cursor": None,
            "agenda_scan_complete": True, "campaign_meta": meta,
            "publication_ready": False, "public_writes": 0,
        }
        self.assertIsNone(_validate_segment(base, AGENDA, meta))
        invalid_cases = [
            good + good,
            [{"begin": "2026-12-12T09:00:00",
              "end": "2026-12-12T09:45:00"}],
            [{"begin": "2026-12-12T09:00:00+01:00",
              "end": "2026-12-12T08:45:00+01:00"}],
            [{"begin": "2026-12-12T09:00:00+01:00",
              "end": "2026-12-12T09:45:00+01:00", "approved": True}],
            good * (MAX_TIMINGS + 1),
        ]
        for invalid in invalid_cases:
            with self.subTest(size=len(invalid)), self.assertRaisesRegex(
                    ValueError, "invalid_private_agenda_segment"):
                forged = dict(base)
                forged["event_leads"] = [
                    dict(base["event_leads"][0],
                         explicit_source_session_intervals=invalid)]
                _validate_segment(forged, AGENDA, meta)



if __name__ == "__main__":
    unittest.main()
