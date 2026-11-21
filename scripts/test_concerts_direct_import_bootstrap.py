"""Reproduce GitHub Actions direct execution import context, without private data."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConcertsPublisherDirectImportTests(unittest.TestCase):
    def test_package_contracts_import_when_executed_outside_repo_root(self):
        # Actions invokes publisher as script; Python adds scripts/ and not
        # the project root to sys.path, breaking package-qualified contracts.
        publisher = Path(__file__).resolve().parent / "concerts_cloud_sync.py"
        smoke = (
            "import runpy, sys\n"
            "runpy.run_path(sys.argv[1], run_name='__contracts_import_smoke__')\n"
            "from scripts import concert_published_lineup_contract\n"
            "from scripts import concert_existing_venue_contract\n"
            "assert hasattr(concert_published_lineup_contract, 'plan')\n"
            "assert hasattr(concert_existing_venue_contract, 'validate')\n"
        )
        with tempfile.TemporaryDirectory() as other_dir:
            result = subprocess.run(
                [sys.executable, "-I", "-c", smoke, str(publisher)],
                cwd=other_dir, capture_output=True, text=True, timeout=35)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
