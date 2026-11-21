"""Offline tests for resuming all private OA event handoffs with no publisher."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_private_national_handoff_rotation import (
    run_rotation, segment_files, STATE_NAME, main,
)
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA

DAY = date(2026, 11, 21)
DIGEST = "a" * 64
KEY = "oa_pk_offline_private_handoff_rotation"


def index():
    return {
        "schema": INDEX_SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "publication_ready": False, "public_writes": 0,
        "new_agenda_candidates": [{
            "agenda_uid": 719191, "agenda_slug": "agenda-demo",
            "source_identity_only": True, "publisher_enabled": False,
        }, {
            "agenda_uid": 719192, "agenda_slug": "agenda-next",
            "source_identity_only": True, "publisher_enabled": False,
        }],
    }


def lead(uid, agenda_uid, slug):
    return {
        "agenda_uid": agenda_uid, "agenda_slug": slug,
        "event_uid": uid, "title": "Spectacle de marionnettes pour enfants",
        "editorial_category_proposal": "spectacle-jeunesse",
        "explicit_source_session_days": ["2026-12-12"],
        "publication_ready": False, "public_writes": 0,
    }


def segment(idx=0, seq=0, size=15):
    uid = 719191 + idx
    slug = "agenda-demo" if idx == 0 else "agenda-next"
    leads = [lead(10000 + i + seq * 100, uid, slug) for i in range(size)]
    return {
        "schema": "ptitesondes.private_oa_agenda_event_exploration.v1",
        "mode": "private_research_event_leads_only",
        "agenda_uid": uid, "agenda_slug": slug,
        "counts": {"pages_read": 1, "public_event_uids_seen": size},
        "event_leads": leads,
        "next_cursor": None, "agenda_scan_complete": True,
        "no_publisher_bridge": True, "publication_ready": False,
        "public_writes": 0,
        "campaign_meta": {
            "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
            "agenda_index": idx, "segment": seq, "start_cursor": None,
        },
    }


def operator(document, digest, record, day, key, *, offset):
    count = len(record["event_leads"])
    end = min(count, offset + 12)
    remaining = record["event_leads"][offset:end]
    return {
        "schema": "ptitesondes.private_national_oa_intake_handoff.v1",
        "mode": "private_intake_research_only", "backlog_leads": [],
        "research_holds": [{
            "event_uid": lead["event_uid"],
            "reason": "direct_event_read_unavailable",
        } for lead in remaining],
        "counts": ({"direct_event_read_unavailable": len(remaining)}
                   if remaining else {}),
        "events_examined": end - offset,
        "next_offset": end, "finished_segment": end == count,
        "publisher_connected": False, "publication_ready": False,
        "safe_to_publish": False, "public_writes": 0,
    }


def private_dirs(tmp):
    root = Path(tmp)
    source, output = root / "segments", root / "handoffs"
    source.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    return source, output


def write_segment(folder, data, idx=0, seq=0):
    path = folder / f"agenda-{idx:04d}-segment-{seq:04d}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class RotationTests(unittest.TestCase):
    def test_automatic_page_resume_without_reexamining_old_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            write_segment(source, segment(size=15))
            work = Mock(wraps=operator)
            first = run_rotation(index(), DIGEST, DAY, source, output,
                                 public_key=KEY, steps=1, operator=work)
            self.assertEqual(first["events_directly_rechecked"], 12)
            self.assertEqual(first["next_offset"], 12)
            self.assertFalse(first["currently_caught_up"])
            second = run_rotation(index(), DIGEST, DAY, source, output,
                                  public_key=KEY, steps=1, operator=work)
            self.assertEqual(second["events_directly_rechecked"], 3)
            self.assertEqual(second["next_segment_index"], 1)
            self.assertTrue(second["currently_caught_up"])
            self.assertEqual([c.kwargs["offset"] for c in work.call_args_list],
                             [0, 12])
            self.assertTrue((output / "handoff-0000-000.json").exists())
            self.assertTrue((output / "handoff-0000-012.json").exists())
            self.assertFalse((output / ".national-handoff-rotation.lock").exists())

    def test_new_appended_campaign_segment_is_discovered_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            write_segment(source, segment(idx=0, size=1))
            a = run_rotation(index(), DIGEST, DAY, source, output,
                             public_key=KEY, operator=operator)
            self.assertTrue(a["currently_caught_up"])
            self.assertEqual(a["next_segment_index"], 1)
            write_segment(source, segment(idx=1, size=1), idx=1)
            b = run_rotation(index(), DIGEST, DAY, source, output,
                             public_key=KEY, operator=operator)
            self.assertEqual(b["events_directly_rechecked"], 1)
            self.assertEqual(b["next_segment_index"], 2)
            self.assertEqual(b["segments_available"], 2)

    def test_crash_after_chunk_write_recovers_exact_report_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            record = segment(size=2)
            filename = write_segment(source, record)
            raw = filename.read_bytes()
            saved = operator(index(), DIGEST, record, DAY, KEY, offset=0)
            saved["rotation_meta"] = {
                "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
                "segment_filename": filename.name,
                "segment_sha256": sha256(raw).hexdigest(),
                "start_offset": 0,
            }
            (output / "handoff-0000-000.json").write_text(
                json.dumps(saved), encoding="utf-8")
            network = Mock(side_effect=AssertionError("No duplicate reading"))
            result = run_rotation(index(), DIGEST, DAY, source, output,
                                  public_key=KEY, operator=network)
            self.assertEqual(result["recovered_chunks"], 1)
            self.assertTrue(result["currently_caught_up"])
            network.assert_not_called()

    def test_forged_recovery_is_refused_before_state_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            filename = write_segment(source, segment(size=1))
            r = operator(index(), DIGEST, segment(size=1), DAY, KEY, offset=0)
            r["rotation_meta"] = {
                "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
                "segment_filename": filename.name,
                "segment_sha256": "a" * 64, "start_offset": 0,
            }
            (output / "handoff-0000-000.json").write_text(
                json.dumps(r), encoding="utf-8")
            network = Mock(side_effect=AssertionError("No API with forged output"))
            with self.assertRaisesRegex(ValueError, "invalid_recovered_private_handoff"):
                run_rotation(index(), DIGEST, DAY, source, output,
                             public_key=KEY, operator=network)
            network.assert_not_called()
            self.assertFalse((output / STATE_NAME).exists())

    def test_forged_recovered_lead_cannot_swap_uid_or_session_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            filename = write_segment(source, segment(size=1))
            document = segment(size=1)
            digest = sha256(filename.read_bytes()).hexdigest()
            for altered in ("uid", "date", "rights"):
                report = operator(index(), DIGEST, document, DAY, KEY, offset=0)
                if altered == "uid":
                    report["research_holds"][0]["event_uid"] = 999999
                elif altered == "date":
                    report["backlog_leads"] = [{
                        "title": document["event_leads"][0]["title"],
                        "source_url": "https://openagenda.com/agenda-demo/events/10000_example",
                        "date_start": "2026-12-14", "date_end": "2026-12-14",
                        "city": "Montpellier", "venue": "Place de la Comédie",
                        "reason": "Découverte OpenAgenda nationale à vérifier : organisateur, catégorie, séances, accès public, lieu, géolocalisation, droits et doublons",
                        "collector": "openagenda-v2", "external_id": "10000",
                    }]
                else:
                    report["publication_ready"] = True
                report["rotation_meta"] = {
                    "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
                    "segment_filename": filename.name,
                    "segment_sha256": digest, "start_offset": 0,
                }
                location = output / "handoff-0000-000.json"
                location.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(ValueError):
                    run_rotation(index(), DIGEST, DAY, source, output,
                                 public_key=KEY, operator=Mock(
                                     side_effect=AssertionError("No fetch")))
                self.assertFalse((output / STATE_NAME).exists())
                location.unlink()

    def test_gapped_segment_sequence_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            write_segment(source, segment(idx=1, size=1), idx=1)
            with self.assertRaisesRegex(ValueError, "noncontiguous"):
                segment_files(source)
            with self.assertRaisesRegex(ValueError, "noncontiguous"):
                run_rotation(index(), DIGEST, DAY, source, output,
                             public_key=KEY, operator=operator)

    def test_dry_run_never_writes_or_calls_live_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = private_dirs(tmp)
            data = index()
            raw = json.dumps(data).encode("utf-8")
            filename = write_segment(source, segment(size=1))
            report = json.loads(filename.read_text(encoding="utf-8"))
            report["campaign_meta"]["source_sha256"] = sha256(raw).hexdigest()
            filename.write_text(json.dumps(report), encoding="utf-8")
            path = Path(tmp) / "index.json"
            path.write_bytes(raw)
            with patch.object(sys, "argv", [
                "prog", "--private-agenda-index-report", str(path),
                "--private-campaign-segments", str(source),
                "--private-output-dir", str(output), "--day", DAY.isoformat(),
            ]), patch(
                "ptitesondes_private_national_handoff_rotation.handoff",
                side_effect=AssertionError("No network on dry-run")):
                main()
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
