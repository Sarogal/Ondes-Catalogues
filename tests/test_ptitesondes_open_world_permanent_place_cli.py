"""Exercise the real file-reader/CLI boundary without network access."""
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import ptitesondes_open_world_permanent_place_research as mod
from test_ptitesondes_open_world_permanent_place_research import report, row

DAY = date(2026, 11, 26)


class PlaceResearchCLITests(unittest.TestCase):
    def test_real_cli_initial_and_resume_from_written_private_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            qualification, output = root / "qualification.json", root / "state.json"
            qualification.write_text(json.dumps(report(row())), encoding="utf-8")
            args = ["research", "--qualification", str(qualification),
                    "--previous", str(output), "--output", str(output),
                    "--date", DAY.isoformat()]
            real_cycle = mod.cycle
            def offline_cycle(report, previous, today, **kwargs):
                return real_cycle(report, previous, today,
                    osm_fetch=lambda *_: {"elements": []},
                    page_read=lambda _: self.fail("unexpected page read"), **kwargs)
            with patch.object(sys, "argv", args), patch.object(mod, "cycle", side_effect=offline_cycle):
                for expected in (1, 2):
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        mod.main()
                    summary = json.loads(stdout.getvalue())
                    state = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(summary["examined"], 1)
                    self.assertEqual(summary["stored_private_results"], 1)
                    self.assertEqual(state["cursor"]["sequence"], expected)
                    self.assertFalse(state["records"][0]["public_eligible"])

    def test_bad_previous_state_cannot_overwrite_existing_bytes_or_leak(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            qualification, output = root / "qualification.json", root / "state.json"
            qualification.write_text(json.dumps(report(row())), encoding="utf-8")
            output.write_text("private non-json secret", encoding="utf-8")
            args = ["research", "--qualification", str(qualification),
                    "--previous", str(output), "--output", str(output),
                    "--date", DAY.isoformat()]
            stdout = StringIO()
            with patch.object(sys, "argv", args), redirect_stdout(stdout), self.assertRaises(SystemExit):
                mod.main()
            self.assertEqual(json.loads(stdout.getvalue()), {
                "error_stage": "read_previous", "publication_ready": False, "public_writes": 0})
            self.assertEqual(output.read_text(encoding="utf-8"), "private non-json secret")
            self.assertNotIn(temp, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
