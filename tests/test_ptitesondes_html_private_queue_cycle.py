"""Offline private HTML queue stage security tests: no credentials or network."""
from contextlib import redirect_stdout
from datetime import date, datetime
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_nonmusical_private_queue_handoff import _row_from_proof
from ptitesondes_html_private_queue_cycle import (
    SCHEMA, STORAGE_RELATIVE, _load_queue, _private_target,
    _registered_adapters, _stage_queue, execute_cycle, main,
)


def row(clock="09:15"):
    return _row_from_proof({
        "source_url": "https://mpt.montpellier.fr/evenement/atelier",
        "source_title_identity_only": "Atelier sensoriel en famille",
        "city": "Montpellier", "venue": "Maison pour tous Albert Camus",
        "category": "atelier-sensoriel", "date_start": "2026-11-22",
        "start_local": clock,
    }, {"stage": "institutional_source_policy_pending"}, date(2026, 11, 20), None)


def manifest(extra=()):
    return {"entries": [{
        "source_id": "montpellier-mpt",
        "approved_host": "mpt.montpellier.fr",
        "index_url": "https://mpt.montpellier.fr/evenements",
        "child_prefix": "/evenement/",
    }, *extra]}


class HtmlPrivateQueueCycleTests(unittest.TestCase):
    NOW = datetime(2026, 11, 20, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))

    def test_curated_manifest_only_supported_adapter_is_used(self):
        targets = _registered_adapters(manifest([{
            "source_id": "other-town",
            "approved_host": "cultural.example.org",
            "index_url": "https://cultural.example.org/agenda",
            "child_prefix": "/sortie/",
        }]))
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][0], "montpellier_mpt")
        self.assertEqual(targets[0][1]["exact_index_url"],
                         "https://mpt.montpellier.fr/evenements")
        self.assertEqual(targets[0][2], "Europe/Paris")

    def test_no_source_or_unknown_adapter_not_rejected_as_publication(self):
        report = execute_cycle(
            [], self.NOW, manifest={"entries": [{
                "source_id": "future", "approved_host": "official.example.org",
                "child_prefix": "/evenement/", "index_url": "https://official.example.org/agenda",
            }]}, context={})
        self.assertEqual(report["queue"], [])
        self.assertEqual(report["report"]["unrecognized_adapters"], 1)
        self.assertEqual(report["report"]["sources_sampled"], 0)
        self.assertFalse(report["report"]["publisher_connected"])

    def test_exact_two_session_records_survive_on_source_recovery(self):
        first = row()
        second = row("10:30")
        calls = []

        def runner(existing, pin, adapter, today, **kw):
            calls.append((pin, adapter, today))
            return {
                "queue": [first, second],
                "report": {
                    "publication_ready": False, "public_writes": 0,
                    "publisher_connected": False,
                    "new_private_reviews": 2,
                    "rechecked_private_reviews": 0,
                },
                "public_funnel_report": {
                    "publication_ready": False, "public_writes": 0,
                    "child_pages_read": 1,
                },
            }

        result = execute_cycle(
            [], self.NOW, manifest=manifest(), context={}, runner=runner)
        self.assertEqual(result["report"]["new_private_reviews"], 2)
        self.assertEqual(len(result["queue"]), 2)
        self.assertEqual({r["start_local"] for r in result["queue"]},
                         {"09:15", "10:30"})
        self.assertEqual(calls[0][1], "montpellier_mpt")
        self.assertFalse(result["report"]["publication_ready"])
        self.assertEqual(result["report"]["public_writes"], 0)

        def inaccessible(*a, **kw):
            raise OSError("https://private.test/NEVER_IN_LOG")
        fail = execute_cycle(
            result["queue"], self.NOW,
            manifest=manifest(), context={}, runner=inaccessible)
        self.assertEqual(fail["queue"], result["queue"])
        self.assertEqual(fail["report"]["sources_unavailable"], 1)
        self.assertNotIn("private.test", json.dumps(fail["report"]))

    def test_rotation_covers_sources_beyond_eight_batches(self):
        from ptitesondes_html_private_queue_cycle import READ_ONLY_ADAPTERS
        sources = []
        extra = {}
        # 24 distinct institutional adapters force 12 batches at size 2.
        for n in range(24):
            host = f"official{n}.example.org"
            name = f"adapter_{n}"
            extra[name] = {
                "host": host, "child_path": "/evenement/",
                "timezone": "Europe/Paris",
            }
            sources.append({
                "source_id": f"synthetic-{n}", "approved_host": host,
                "index_url": f"https://{host}/programme",
                "child_prefix": "/evenement/",
            })
        names = []
        def runner(existing, pin, adapter, day, **opts):
            names.append(adapter)
            return {
                "queue": existing,
                "report": {
                    "publication_ready": False, "public_writes": 0,
                    "publisher_connected": False,
                    "new_private_reviews": 0, "rechecked_private_reviews": 0,
                },
                "public_funnel_report": {
                    "publication_ready": False, "public_writes": 0,
                    "child_pages_read": 1,
                },
            }
        with patch.dict(READ_ONLY_ADAPTERS, extra):
            for batch in range(12):
                res = execute_cycle(
                    [], self.NOW, batch=batch, max_sources=2,
                    manifest={"entries": sources}, context={}, runner=runner)
                self.assertEqual(res["report"]["source_batches_total"], 12)
                self.assertEqual(res["report"]["sources_selected"], 2)
            self.assertEqual(len(set(names)), 24)
            self.assertEqual(len(names), 24)

    def test_unavailable_index_is_not_counted_as_a_sample(self):
        def empty(existing, pin, adapter, day, **opts):
            return {
                "queue": existing,
                "report": {
                    "publication_ready": False, "public_writes": 0,
                    "publisher_connected": False,
                    "new_private_reviews": 0, "rechecked_private_reviews": 0,
                },
                "public_funnel_report": {
                    "publication_ready": False, "public_writes": 0,
                    "child_pages_read": 0,
                },
            }
        result = execute_cycle(
            [row()], self.NOW, manifest=manifest(), context={}, runner=empty)
        self.assertEqual(result["report"]["sources_sampled"], 0)
        self.assertEqual(result["report"]["sources_unavailable"], 1)
        self.assertEqual(result["queue"], [row()])

    def test_empty_batch_and_invalid_options_fail_closed(self):
        r = execute_cycle([], self.NOW, batch=4, manifest={"entries": []}, context={})
        self.assertEqual(r["queue"], [])
        self.assertEqual(r["report"]["sources_selected"], 0)
        for invalid in (-1, "1", True):
            with self.assertRaises(ValueError):
                execute_cycle([], self.NOW, batch=invalid, manifest=manifest(), context={})

    def test_private_stage_and_existing_file_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "html-review-candidates.json"
            self.assertEqual(_load_queue(path), [])
            _stage_queue(path, [row(), row("10:30")])
            data = _load_queue(path)
            self.assertEqual(len(data), 2)
            self.assertEqual({r["start_local"] for r in data}, {"09:15", "10:30"})
            data[0]["approved"] = True
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                _load_queue(path)
            previous = path.read_bytes()
            with self.assertRaises(ValueError):
                _stage_queue(path, data)
            self.assertEqual(path.read_bytes(), previous)

    def test_fake_private_branch_and_remote_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subprocess.run(
                ["git", "init", "-q", "-b", "automation/ptitesondes-intake",
                 str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin",
                 "https://github.com/Sarogal/PtitesOndes"],
                check=True, capture_output=True)
            self.assertEqual(_private_target(root), root / STORAGE_RELATIVE)
            subprocess.run(
                ["git", "-C", str(root), "remote", "set-url", "origin",
                 "https://github.com/attacker/repo"],
                check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, "private_git_remote_wrong"):
                _private_target(root)
            subprocess.run(
                ["git", "-C", str(root), "remote", "set-url", "origin",
                 "https://github.com/Sarogal/PtitesOndes"],
                check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "checkout", "-q", "-b", "main"],
                check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, "private_git_branch_wrong"):
                _private_target(root)

    def test_main_preview_cannot_write_or_reveal_private_row(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "html-review-candidates.json"
            output = io.StringIO()
            with patch("sys.argv", [
                "worker", "--mode", "preview", "--state-checkout", temp]), patch(
                "ptitesondes_html_private_queue_cycle._private_target",
                return_value=target), patch(
                "ptitesondes_html_private_queue_cycle._load_queue",
                return_value=[]), patch(
                "ptitesondes_html_private_queue_cycle.execute_cycle",
                return_value={
                    "queue": [row()],
                    "report": {
                        "schema": SCHEMA, "total_private_reviews": 1,
                        "public_writes": 0, "publisher_connected": False,
                    },
                }), patch(
                "ptitesondes_html_private_queue_cycle._stage_queue") as stage:
                with redirect_stdout(output):
                    main()
                stage.assert_not_called()
            self.assertFalse(target.exists())
            self.assertNotIn("mpt.montpellier.fr", output.getvalue())
            self.assertNotIn("Maison pour tous", output.getvalue())


if __name__ == "__main__":
    unittest.main()
