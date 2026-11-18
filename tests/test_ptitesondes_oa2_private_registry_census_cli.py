"""Read-only private census CLI: no private details in stdout, no writes."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_oa2_private_registry_census_cli import main, run
from test_ptitesondes_openagenda_v2_institutional_delegation import (
    direct_case, REVIEWED, TODAY,
)


class PrivateRegistryCLI(unittest.TestCase):
    def test_private_json_aggregate_output_only(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            lead = direct_case()["lead"]
            rows = [lead, dict(lead, date_start="invalid")]
            backlog = folder / "private-backlog.json"
            registry = folder / "trusted-owners.json"
            backlog.write_text(json.dumps(rows), encoding="utf-8")
            registry.write_text(json.dumps([REVIEWED]), encoding="utf-8")
            output = io.StringIO()
            before = sorted(x.name for x in folder.iterdir())
            with contextlib.redirect_stdout(output):
                main(["--private-backlog", str(backlog),
                      "--independently-curated-registry", str(registry),
                      "--today", "2026-11-18"])
            after = sorted(x.name for x in folder.iterdir())
            result = json.loads(output.getvalue())
            self.assertEqual(before, after)
            self.assertEqual(result["counts"]["raw_rows"], 2)
            self.assertEqual(result["counts"]["invalid_or_missing_date"], 1)
            self.assertEqual(
                result["counts"]["institution_pin_selected_for_verification_only"], 1)
            self.assertFalse(result["approval_granted"])
            self.assertEqual(result["public_writes"], 0)
            for sensitive in (
                lead["source_url"], lead["title"],
                REVIEWED["institution_host"], REVIEWED["exact_page_url"],
            ):
                self.assertNotIn(sensitive, output.getvalue())

    def test_invalid_date_and_json_rejected_without_disclosing_private_paths(self):
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root) / "private-secret.json"
            registry = Path(root) / "registry.json"
            bad.write_text("NOT JSON", encoding="utf-8")
            registry.write_text("[]", encoding="utf-8")
            with self.assertRaises(SystemExit) as e:
                main(["--private-backlog", str(bad),
                      "--independently-curated-registry", str(registry),
                      "--today", "2026-11-18"])
            self.assertEqual(str(e.exception),
                             "private_registry_census_unavailable")
            self.assertNotIn(str(bad), str(e.exception))
            with self.assertRaises(SystemExit):
                main(["--private-backlog", str(bad),
                      "--independently-curated-registry", str(registry),
                      "--today", "18-11-2026"])

    def test_missing_registry_cannot_be_implicitly_approved(self):
        with tempfile.TemporaryDirectory() as root:
            backlog = Path(root) / "backlog.json"
            no_registry = Path(root) / "no-registry.json"
            backlog.write_text(json.dumps([direct_case()["lead"]]), encoding="utf-8")
            with self.assertRaises((ValueError, OSError)):
                run(str(backlog), str(no_registry), "2026-11-18")


if __name__ == "__main__":
    unittest.main()
