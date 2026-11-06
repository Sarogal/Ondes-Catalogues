"""Regression: the regional CLI must summarize its scan without leaking private data."""
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import regional_festival_discovery as regional


class RegionalCliTests(unittest.TestCase):
    def test_main_uses_report_metrics_not_scan_local_variables(self):
        today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
        with tempfile.TemporaryDirectory() as directory:
            intake = Path(directory) / "private-intake"
            intake.mkdir()
            (intake / "source-watch-state.json").write_text(
                json.dumps({"schema": "grossesondes.source-watch.v1"}),
                encoding="utf-8",
            )
            report_path = Path(directory) / "official-report.json"
            report_path.write_text(
                json.dumps({"schema": "grossesondes.source-watch-report.v1",
                            "date": today}), encoding="utf-8",
            )
            original_scan = regional.scan_regional_indexes

            def offline_scan(report, state, indexes, day, **kwargs):
                return original_scan(
                    report, state, indexes, day,
                    fetch=lambda url: "<main><p>Agenda institutionnel</p></main>",
                    **kwargs,
                )

            output = io.StringIO()
            with (
                patch.object(regional, "load_verified_archive_hints",
                             return_value=({}, "UNAVAILABLE_OR_INVALID", 0)),
                patch.object(regional, "scan_regional_indexes",
                             side_effect=offline_scan),
                patch.object(sys, "argv", [
                    "regional_festival_discovery.py",
                    "--intake", str(intake),
                    "--report", str(report_path),
                    "--limit", "4",
                ]),
                redirect_stdout(output),
            ):
                regional.main()

            summary_line = next(line for line in output.getvalue().splitlines()
                                if line.startswith("DECOUVERTE_REGIONALE:"))
            summary = json.loads(summary_line.split(": ", 1)[1])
            updated = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["visible_articles"],
                             updated["regional_festival_visible_articles_review_only"])
            self.assertEqual(summary["article_clues_new"],
                             updated["regional_festival_article_clues_new_review_only"])
            self.assertEqual(summary["published"], 0)
            self.assertEqual(updated["regional_festival_publications"], 0)


if __name__ == "__main__":
    unittest.main()
