"""No-network checks of the PRIVATE outings quality dashboard."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_daily_quality_dashboard import daily_dashboard, markdown_status


def catalogue():
    return {"version": 3, "updated_at": "2026-11-04T09:57:54+01:00",
            "events": [{"id": "historic-1"}, {"id": "historic-2"}]}


def write(folder, name, doc):
    (folder / name).write_text(json.dumps(doc), encoding="utf-8")


def collecting(day="2026-11-11", backlog=244):
    return {"day": day, "sources_interrogees": 22,
            "evenements_examines": 223, "seances_pertinentes": 255,
            "decouvertes_nouvelles_en_attente": 0, "en_attente_total": backlog}


def qualifying(day="2026-11-11", slot=0, backlog=244, eligible=31):
    return {"day": day, "slot": slot, "mode": "private_diagnostic_only",
            "backlog_total": backlog, "eligible": eligible,
            "checked": 2, "accepted_preflight": 0, "rejected": 2,
            "reason_groups": {"age_or_audience": 1, "date_or_time": 1}}


def verifying(day="2026-11-11"):
    return {"day": day, "mode": "private_patch_only",
            "new_approved_privately": 0, "public_writes": 0}


class DailyDashboardTests(unittest.TestCase):
    def test_reconciles_counts_without_claiming_pages_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write(folder, "2026-11-11.json", collecting())
            write(folder, "qualification-2026-11-11-slot0.json", qualifying())
            write(folder, "qualification-2026-11-11-slot1.json",
                  qualifying(slot=1, backlog=245, eligible=32))
            write(folder, "verification-2026-11-11.json", verifying())
            report = daily_dashboard(folder, catalogue(), date(2026, 11, 11))
            day = report["days"][0]
            self.assertEqual(report["public_catalogue"]["events"], 2)
            self.assertEqual(day["checks"], 4)
            self.assertEqual(day["eligible"], 32)
            self.assertEqual(day["rejected_decisions"], 4)
            self.assertEqual(day["private_approvals"], 0)
            self.assertEqual(day["public_writes_reported_by_private_intake"], 0)
            self.assertNotIn("published", day)
            doc = markdown_status(report)
            self.assertIn("pas", doc)
            self.assertIn("244", doc)
            self.assertNotIn("https://", doc)

    def test_missing_reports_are_unknown_not_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write(folder, "2026-11-11.json", collecting())
            report = daily_dashboard(folder, catalogue(), date(2026, 11, 11))
            row = report["days"][0]
            self.assertEqual(row["qualification_slots"], 0)
            self.assertIsNone(row["eligible"])
            self.assertIsNone(row["private_approvals"])
            self.assertIsNone(row["public_writes_reported_by_private_intake"])

    def test_wrong_day_status_or_reason_counts_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write(folder, "2026-11-11.json", collecting())
            q = qualifying()
            for changed in (
                dict(q, day="2026-11-12"),
                dict(q, rejected=3),
                dict(q, reason_groups={"PRIVATE_SECRET": 2}),
                dict(q, eligible=-1),
                dict(q, mode="automatic_publish"),
            ):
                write(folder, "qualification-2026-11-11-slot0.json", changed)
                with self.assertRaises(ValueError):
                    daily_dashboard(folder, catalogue(), date(2026, 11, 11))

    def test_public_catalogue_history_and_schema_are_guarded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write(folder, "2026-11-11.json", collecting())
            for bad in (
                {"version": 4, "events": []},
                dict(catalogue(), events=[{"id": "a"}, {"id": "a"}]),
                dict(catalogue(), updated_at=""),
            ):
                with self.assertRaises(ValueError):
                    daily_dashboard(folder, bad, date(2026, 11, 11))

    def test_history_window_does_not_invent_missing_collection_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write(folder, "2026-11-09.json", collecting(day="2026-11-09"))
            write(folder, "2026-11-11.json", collecting())
            report = daily_dashboard(folder, catalogue(), date(2026, 11, 11))
            self.assertEqual([x["day"] for x in report["days"]],
                             ["2026-11-09", "2026-11-11"])


if __name__ == "__main__":
    unittest.main()
