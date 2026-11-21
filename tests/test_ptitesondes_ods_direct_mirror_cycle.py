"""Private file/stage and secret-redaction tests for ODS direct mirror audit."""
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_ods_direct_mirror_absence_audit import (
    SCHEMA as AUDIT_SCHEMA, _id,
)
from ptitesondes_ods_direct_mirror_cycle import (
    RELATIVE, _read_existing, run_private_direct_cycle,
)

NOW = datetime(2026, 11, 20, 13, tzinfo=ZoneInfo("Europe/Paris"))


def checkout(root):
    subprocess.run(
        ["git", "init", "-q", "-b", "automation/ptitesondes-intake", str(root)],
        check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin",
         "https://github.com/Sarogal/PtitesOndes"],
        check=True, capture_output=True)
    (root / "automation-intake/ptitesondes").mkdir(parents=True)
    (root / "automation").mkdir()
    (root / "automation-intake/ptitesondes/backlog.json").write_text(
        json.dumps([{
            "collector": "openagenda-v2", "external_id": "12345",
            "source_url": "https://openagenda.com/fr/agenda-de-test/events/12345_titre",
            "date_start": "2026-12-10", "date_end": "2026-12-10",
            "title": "Titre unique confidentiel",
        }]), encoding="utf-8")
    (root / "automation/sources.json").write_text(
        json.dumps({"schema": "ptitesondes.sources.v1",
                    "openagenda_agendas": [551]}), encoding="utf-8")


def private_row():
    return {
        "schema": AUDIT_SCHEMA,
        "audit_id": _id(551, "12345", "2026-12-10"),
        "event_uid": "12345", "agenda_uid": 551,
        "date_start": "2026-12-10",
        "state": "mirror_absent_direct_day_and_title_confirmed",
        "first_checked_on": "2026-11-20",
        "last_checked_on": "2026-11-20",
        "organizer_independently_verified": False,
        "rights_reviewed": False, "venue_geo_verified": False,
        "family_audience_verified": False, "publisher_connected": False,
        "publication_ready": False, "approved": False, "public_writes": 0,
    }


def evaluator(leads, previous, agendas, key, today, **kwargs):
    assert len(leads) == 1 and agendas == [551] and key == "oa_pk_private"
    return {
        "private_rows": [private_row()],
        "report": {
            "schema": AUDIT_SCHEMA, "mirror_uid_absent": 1,
            "direct_api_matched_day_and_title": 1,
            "public_writes": 0, "publisher_connected": False,
            "publication_ready": False, "approved": False,
        },
    }


class PrivateDirectMirrorCycleTests(unittest.TestCase):
    def test_preview_only_reads_privates_and_never_exports_sensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            report = run_private_direct_cycle(
                root, NOW, mode="preview", public_key="oa_pk_private",
                evaluator=evaluator)
            self.assertFalse((root / RELATIVE).exists())
            self.assertIn("direct_api_matched_day_and_title", report)
            blob = json.dumps(report)
            for secret in ("12345", "Titre unique", "oa_pk_private",
                           "agenda-de-test", "source_url"):
                self.assertNotIn(secret, blob)
            self.assertFalse(report["approved"])
            self.assertEqual(report["public_writes"], 0)

    def test_stage_writes_private_only_and_reopens_checked_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            report = run_private_direct_cycle(
                root, NOW, mode="stage", public_key="oa_pk_private",
                evaluator=evaluator)
            path = root / RELATIVE
            self.assertTrue(path.is_file())
            content = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(content["schema"], AUDIT_SCHEMA)
            self.assertEqual(content["private_rows"], [private_row()])
            self.assertEqual(_read_existing(path), [private_row()])
            self.assertEqual(report["public_writes"], 0)
            self.assertFalse((root / "ptitesondes/sorties.json").exists())

    def test_forged_approval_and_symlink_stay_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            fake = lambda *args, **kwargs: dict(
                evaluator(*args, **kwargs),
                private_rows=[dict(private_row(), approved=True)])
            with self.assertRaises(ValueError):
                run_private_direct_cycle(root, NOW, mode="stage",
                                         public_key="oa_pk_private",
                                         evaluator=fake)
            self.assertFalse((root / RELATIVE).exists())
            outside = root / "outside.txt"
            outside.write_text("keep", encoding="utf-8")
            try:
                (root / RELATIVE).symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not supported")
            with self.assertRaises(ValueError):
                run_private_direct_cycle(root, NOW, mode="stage",
                                         public_key="oa_pk_private",
                                         evaluator=evaluator)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_wrong_remote_or_branch_rejected_before_key_and_source_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            subprocess.run(
                ["git", "-C", str(root), "remote", "set-url", "origin",
                 "https://github.com/malicious/Other"],
                check=True, capture_output=True)
            with self.assertRaises(ValueError):
                run_private_direct_cycle(root, NOW, mode="preview",
                                         public_key="oa_pk_private",
                                         evaluator=evaluator)
            self.assertFalse((root / RELATIVE).exists())

    def test_empty_key_and_broken_configuration_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            with self.assertRaises(ValueError):
                run_private_direct_cycle(root, NOW, public_key="",
                                         evaluator=evaluator)
            (root / "automation/sources.json").write_text(
                json.dumps({"openagenda_agendas": [551]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                run_private_direct_cycle(root, NOW, public_key="oa_pk_private",
                                         evaluator=evaluator)


    def test_empty_manifest_still_allows_opt_in_private_research(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            (root / "automation/sources.json").write_text(
                json.dumps({"schema": "ptitesondes.sources.v1",
                            "openagenda_agendas": []}), encoding="utf-8")
            seen = []
            def inspect(leads, previous, agendas, key, today, **kwargs):
                self.assertEqual(agendas, [])
                self.assertTrue(callable(kwargs["agenda_discovery"]))
                seen.append(True)
                return evaluator(leads, previous, [551], key, today)
            report = run_private_direct_cycle(
                root, NOW, mode="preview", public_key="oa_pk_private",
                evaluator=inspect, discover_unconfigured=True)
            self.assertEqual(seen, [True])
            self.assertFalse(report["publication_ready"])
            self.assertFalse((root / RELATIVE).exists())


    def test_unconfigured_slug_research_is_opt_in_preview_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checkout(root)
            received = []
            def inspect(leads, previous, agendas, key, today, **kwargs):
                received.append(kwargs)
                assert callable(kwargs["agenda_discovery"])
                return evaluator(leads, previous, agendas, key, today)
            report = run_private_direct_cycle(
                root, NOW, mode="preview", public_key="oa_pk_private",
                evaluator=inspect, discover_unconfigured=True)
            self.assertEqual(len(received), 1)
            self.assertIs(report["publication_ready"], False)
            self.assertEqual(report["public_writes"], 0)
            self.assertFalse((root / RELATIVE).exists())
            with self.assertRaises(ValueError):
                run_private_direct_cycle(
                    root, NOW, mode="stage", public_key="oa_pk_private",
                    evaluator=inspect, discover_unconfigured=True)
            with self.assertRaises(ValueError):
                run_private_direct_cycle(
                    root, NOW, mode="preview", public_key="oa_pk_private",
                    evaluator=inspect, discover_unconfigured="true")
            self.assertFalse((root / RELATIVE).exists())


if __name__ == "__main__":
    unittest.main()
