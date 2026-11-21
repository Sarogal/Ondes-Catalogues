"""National private OA -> open-world research: offline admission boundaries."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_national_openworld_research_cycle import (
    research_cycle, _future_original, main, SCHEMA,
)
from ptitesondes_open_world_candidate_rotation import _blank

DAY = date(2026, 11, 21)
KEY = "oa_pk_offline_national_openworld_research"


def entry(uid, category=None, day=DAY + timedelta(days=15),
          n_sessions=2):
    intervals = []
    for i in range(n_sessions):
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        start = start.replace(hour=9) + timedelta(minutes=25 * i)
        intervals.append({
            "begin": start.isoformat(timespec="seconds"),
            "end": (start + timedelta(minutes=20))
                .isoformat(timespec="seconds"),
        })
    lead = {
        "agenda_uid": 95270 + uid, "agenda_slug": "new-agenda-" + str(uid),
        "event_uid": uid, "title": "Spectacle musical pour enfants",
        "city_unverified": "Ville nouvelle",
        "venue_unverified": "Cour intérieure",
        "explicit_source_session_intervals": intervals,
        "editorial_category_proposal": category,
        "publication_ready": False, "public_writes": 0,
    }
    segment = {
        "agenda_uid": lead["agenda_uid"],
        "agenda_slug": lead["agenda_slug"],
        "campaign_meta": {"segment": 0},
        "event_leads": [lead],
    }
    source = {"new_agenda_candidates": [{
        "agenda_uid": lead["agenda_uid"]}]}
    return source, "a" * 64, segment, DAY, 0


def valid_operator(lead, key, today, *, previous_checkpoint,
                   pages_per_cycle, sources_per_cycle):
    assert key == KEY
    assert pages_per_cycle == 2 and sources_per_cycle == 1
    report = _blank("private_rotation_in_progress")
    report["oa_urls_rechecked"] = 1
    report["oa_exact_session_claims_unverified"] = 2
    report["private_checkpoint"] = {
        "schema": "fake_private_checkpoint",
        "seen": (previous_checkpoint or {}).get("seen", 0) + 1,
    }
    return report


class ResearchCycleTests(unittest.TestCase):
    def test_any_new_agenda_organizer_and_venue_can_enter_private_research(self):
        items = [entry(100, category=None), entry(101, "concert"),
                 entry(102, None)]
        reports, state, summary = research_cycle(
            Path("/unused"), DAY, KEY,
            inventory_reader=lambda _: items, operator=valid_operator)
        self.assertEqual(summary["events_examined"], 3)
        self.assertEqual(summary["source_reviews"], 3)
        self.assertEqual(summary["exact_session_claims_unverified"], 6)
        self.assertEqual(len(reports), 3)
        self.assertEqual(state["schema"], SCHEMA)
        self.assertEqual(reports[0]["review"]["private_checkpoint"]["seen"], 1)
        self.assertFalse(summary["publisher_connected"])
        self.assertFalse(summary["publication_ready"])
        self.assertEqual(summary["public_writes"], 0)

    def test_new_event_editorial_proposal_prioritized_without_white_list(self):
        seen = []
        def capture(lead, *args, **kwargs):
            seen.append(lead["event_uid"])
            return valid_operator(lead, *args, **kwargs)
        items = [entry(112), entry(113, "concert"), entry(114)]
        _, state, _ = research_cycle(
            Path("/unused"), DAY, KEY, max_events=1,
            inventory_reader=lambda _: items, operator=capture)
        self.assertEqual(seen, [113])
        _, _, _ = research_cycle(
            Path("/unused"), DAY, KEY, cursor=state, max_events=1,
            inventory_reader=lambda _: items, operator=capture)
        self.assertEqual(len(set(seen)), 2)

    def test_higher_budget_rotates_through_unlisted_candidates_without_skips(self):
        items = [entry(400 + i, category="spectacle-jeunesse"
                       if i % 3 == 0 else None) for i in range(18)]
        seen = []
        def capture(lead, *args, **kwargs):
            seen.append(lead["event_uid"])
            return valid_operator(lead, *args, **kwargs)
        _, first, first_report = research_cycle(
            Path("/unused"), DAY, KEY, max_events=8,
            inventory_reader=lambda _: items, operator=capture)
        self.assertEqual(first_report["events_examined"], 8)
        self.assertEqual(len(set(seen)), 8)
        _, second, second_report = research_cycle(
            Path("/unused"), DAY, KEY, cursor=first, max_events=8,
            inventory_reader=lambda _: items, operator=capture)
        self.assertEqual(second_report["events_examined"], 8)
        self.assertEqual(len(set(seen)), 16)
        _, _, third_report = research_cycle(
            Path("/unused"), DAY, KEY, cursor=second, max_events=2,
            inventory_reader=lambda _: items, operator=capture)
        self.assertEqual(third_report["events_examined"], 2)
        self.assertEqual(len(set(seen)), 18)
        self.assertEqual(third_report["candidates_with_future_sessions"], 18)

    def test_unbounded_cycle_request_does_not_exceed_safe_budget(self):
        with self.assertRaises(ValueError):
            research_cycle(Path("/unused"), DAY, KEY, max_events=9,
                           inventory_reader=lambda _: [entry(400)],
                           operator=valid_operator)

    def test_pending_original_slots_are_retained_without_session_limit(self):
        item = entry(115, "conte-musical", n_sessions=12)
        self.assertEqual(len(_future_original(item, DAY)[
            "explicit_source_session_intervals"]), 12)
        seen = []
        def capture(lead, *args, **kwargs):
            seen.append(lead)
            return valid_operator(lead, *args, **kwargs)
        research_cycle(Path("/unused"), DAY, KEY,
                       inventory_reader=lambda _: [item], operator=capture)
        self.assertEqual(len(seen[0]["explicit_source_session_intervals"]), 12)

    def test_expired_session_skipped_never_promoted_or_synthesized(self):
        expired = entry(110, day=DAY-timedelta(days=2))
        future = entry(111)
        seen = []
        def capture(lead, *args, **kwargs):
            seen.append(lead["event_uid"])
            return valid_operator(lead, *args, **kwargs)
        _, _, summary = research_cycle(
            Path("/unused"), DAY, KEY,
            inventory_reader=lambda _: [expired, future],
            operator=capture)
        self.assertEqual(seen, [111])
        self.assertEqual(summary["candidates_with_future_sessions"], 1)

    def test_resume_opaque_cursor_and_previous_private_checkpoint(self):
        item = entry(117, "eveil-musical")
        _, state, _ = research_cycle(
            Path("/unused"), DAY, KEY,
            inventory_reader=lambda _: [item], operator=valid_operator)
        reports, newer, _ = research_cycle(
            Path("/unused"), DAY, KEY, cursor=state,
            inventory_reader=lambda _: [item], operator=valid_operator)
        self.assertEqual(reports[0]["review"]["private_checkpoint"]["seen"], 2)
        self.assertEqual(newer["last_completed_ref"], state["last_completed_ref"])

    def test_untrusted_research_cannot_self_approve_or_add_public_writes(self):
        def forged(*args, **kwargs):
            r = valid_operator(*args, **kwargs)
            r["publication_ready"] = True
            return r
        with self.assertRaises(ValueError):
            research_cycle(Path("/unused"), DAY, KEY,
                           inventory_reader=lambda _: [entry(116)],
                           operator=forged)

    def test_invalid_private_cursor_fails_closed(self):
        with self.assertRaises(ValueError):
            research_cycle(Path("/unused"), DAY, KEY,
                           cursor={"schema": SCHEMA, "scan_day": DAY.isoformat(),
                                   "last_completed_ref": None,
                                   "checkpoints": {"../../file": {}}},
                           inventory_reader=lambda _: [],
                           operator=valid_operator)

    def test_default_dry_run_never_reads_inputs_or_writes(self):
        args = ["cycle", "--private-observation-root", "/not-found",
                "--private-research-root", "/not-found",
                "--day", DAY.isoformat()]
        with patch.object(sys, "argv", args), patch(
                "ptitesondes_national_openworld_research_cycle._inventory",
                side_effect=AssertionError("no research on dry-run")):
            main()


if __name__ == "__main__":
    unittest.main()
