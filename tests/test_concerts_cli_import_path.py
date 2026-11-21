"""Regression for the actual GitHub Actions CLI launch (not unittest imports)."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts/concerts_cloud_sync.py"
PROBE = r'''
import datetime as dt
import json
import pathlib
import runpy
import sys
script = pathlib.Path(sys.argv[1])
publisher = runpy.run_path(str(script), run_name="__cli_import_probe__")
root = script.parents[1]
original = json.loads((root / "docs/grossesondes/concerts-reference.json").read_text())
candidate, counts = publisher["merge"](
    original, original, {"schema": "grossesondes.concert.approvals.v1",
                         "approvals": []}, dt.date(2026, 11, 21))
assert candidate == original
assert counts["newEvents"] == counts["newVenues"] == 0
'''


class DirectGitHubActionsCliImports(unittest.TestCase):
    def test_sync_direct_cli_can_load_helper_and_execute_publisher(self):
        # -I removes the repository root and PYTHONPATH from interpreter
        # startup. The module itself must install its own stable import path.
        p = subprocess.run([sys.executable, "-I", "-c", PROBE, str(SYNC)],
                           cwd=str(ROOT), capture_output=True, text=True,
                           timeout=35, check=False)
        self.assertEqual(p.returncode, 0,
                         "Publisher CLI import regression: " + p.stderr[-1800:])


if __name__ == "__main__":
    unittest.main()
