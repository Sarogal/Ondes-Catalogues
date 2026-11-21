"""Private national backlog bridge: offline regression and security contract."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_national_backlog_bridge import bridge, _inventory, main, SCHEMA
from ptitesondes_private_national_qualification_handoff import BACKLOG_REASON

TODAY = date(2026, 11, 21)
SCAN_DAY = date(2026, 11, 20)
KEY = "oa_pk_offline_national_bridge_test"


def fixture(uid=12345, day="2026-12-01"):
    event = {"event_uid": uid, "title": "Concert jeunesse inédit",
             "explicit_source_session_days": [day]}
    segment = {"agenda_uid": 101, "agenda_slug": "scene-libre",
               "event_leads": [event]}
    return ({"new_agenda_candidates": [{"agenda_uid": 101}]},
            "a" * 64, segment, SCAN_DAY, 0)


def operator(document, digest, segment, today, key, *,
             offset, max_fetch, source_scan_day):
    assert max_fetch == 1 and source_scan_day == SCAN_DAY
    uid = str(segment["event_leads"][offset]["event_uid"])
    row = {"title": "Concert jeunesse inédit",
           "source_url": f"https://openagenda.com/scene-libre/events/{uid}_concert",
           "date_start": "2026-12-01", "date_end": "2026-12-01",
           "city": "Commune nouvelle", "venue": "Place publique",
           "reason": BACKLOG_REASON, "collector": "openagenda-v2",
           "external_id": uid}
    return {"schema": "ptitesondes.private_national_oa_intake_handoff.v1",
            "mode": "private_intake_research_only",
            "backlog_leads": [row], "research_holds": [],
            "counts": {"private_intake_leads_only": 1},
            "events_examined": 1, "next_offset": offset + 1,
            "finished_segment": offset + 1 == len(segment["event_leads"]),
            "publisher_connected": False, "publication_ready": False,
            "safe_to_publish": False, "public_writes": 0}


class BridgeTests(unittest.TestCase):
    def test_reuses_national_event_handoff_without_publisher(self):
        with patch("ptitesondes_national_backlog_bridge._inventory",
                   return_value=[fixture()]):
            merged, cursor, info = bridge(
                Path("/not-used"), [], TODAY, KEY, operator=operator)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["external_id"], "12345")
        self.assertEqual(info["new_unverified_leads"], 1)
        self.assertFalse(info["publication_ready"])
        self.assertEqual(info["public_writes"], 0)
        self.assertEqual(cursor["schema"], SCHEMA)

    def test_duplicate_from_previous_backlog_not_reinserted(self):
        old = operator(None, None, fixture()[2], TODAY, KEY,
                       offset=0, max_fetch=1, source_scan_day=SCAN_DAY)["backlog_leads"]
        with patch("ptitesondes_national_backlog_bridge._inventory",
                   return_value=[fixture()]):
            result, _, report = bridge(
                Path("/unused"), old, TODAY, KEY, operator=operator)
        self.assertEqual(result, old)
        self.assertEqual(report["new_unverified_leads"], 0)
        self.assertEqual(report["existing_leads_skipped"], 1)

    def test_legacy_identity_conflict_is_held_not_overwritten(self):
        old = operator(None, None, fixture()[2], TODAY, KEY,
                       offset=0, max_fetch=1, source_scan_day=SCAN_DAY)["backlog_leads"]
        old[0]["city"] = "Autre ville"
        with patch("ptitesondes_national_backlog_bridge._inventory",
                   return_value=[fixture()]):
            result, _, report = bridge(
                Path("/unused"), old, TODAY, KEY, operator=operator)
        self.assertEqual(result, old)
        self.assertEqual(report["research_holds"], 1)

    def test_round_robin_advances_across_known_and_unknown_events(self):
        items = [fixture(uid=100 + i) for i in range(3)]
        with patch("ptitesondes_national_backlog_bridge._inventory",
                   return_value=items):
            _, cursor, r1 = bridge(
                Path("/unused"), [], TODAY, KEY, limit=2, operator=operator)
            _, after, r2 = bridge(
                Path("/unused"), [], TODAY, KEY, limit=1,
                cursor=cursor, operator=operator)
        self.assertEqual((r1["events_rechecked"], r2["events_rechecked"]), (2, 1))
        self.assertEqual(after["next_index"], 0)

    def test_untrusted_operator_cannot_claim_publication(self):
        def forged(*args, **kwargs):
            value = operator(*args, **kwargs)
            value["publication_ready"] = True
            return value
        with patch("ptitesondes_national_backlog_bridge._inventory",
                   return_value=[fixture()]):
            with self.assertRaises(ValueError):
                bridge(Path("/unused"), [], TODAY, KEY, operator=forged)

    def test_dry_run_does_not_read_backlog_network_or_write(self):
        with TemporaryDirectory() as temp:
            output = Path(temp) / "output.json"
            args = ["bridge", "--private-observation-root", temp,
                    "--backlog-file", str(Path(temp) / "missing.json"),
                    "--output-file", str(output),
                    "--cursor-file", str(Path(temp) / "cursor.json"),
                    "--day", TODAY.isoformat()]
            with patch.object(sys, "argv", args), patch(
                    "ptitesondes_national_backlog_bridge._inventory",
                    side_effect=AssertionError("no I/O")):
                main()
            self.assertFalse(output.exists())

    def test_absent_observation_yields_unchanged_private_backlog(self):
        with TemporaryDirectory() as temp:
            initial = [{"collector": "openagenda-v2", "external_id": "777",
                        "date_start": "2026-12-01"}]
            merged, _, summary = bridge(Path(temp), initial, TODAY, KEY)
            self.assertEqual(merged, initial)
            self.assertEqual(summary["events_rechecked"], 0)


if __name__ == "__main__":
    unittest.main()
