import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from radio_daily_v9_generator import digest,encode
from test_radio_daily_repair_plan import fixture

TOOLS=Path(__file__).resolve().parent

class BaselineCliTests(unittest.TestCase):
    def test_maintenance_cli_accepts_explicit_successor(self):
        raw,*_=fixture()
        doc=json.loads(raw)
        doc["release_sequence"]=9
        raw=encode(doc)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            baseline=root/"baseline.json"
            baseline.write_bytes(raw)
            out=root/"report.json"
            command=[sys.executable,str(TOOLS/"radio_daily_maintenance_preview.py"),
                     "--baseline",str(baseline),"--output",str(out)]
            rejected=subprocess.run(command,capture_output=True)
            self.assertNotEqual(rejected.returncode,0)
            self.assertFalse(out.exists())
            accepted=subprocess.run(command+["--baseline-sha256",digest(raw)],capture_output=True,text=True)
            self.assertEqual(accepted.returncode,0,accepted.stderr)
            self.assertEqual(json.loads(out.read_bytes())["catalogBaselineSha256"],digest(raw))

    def test_all_maintenance_clis_expose_explicit_anchor(self):
        for name in ("maintenance_preview","repair_preview","repair_confirmation","repair_plan",
                     "status_preview","logo_maintenance","missing_logo","unified_generator"):
            with self.subTest(name=name):
                result=subprocess.run([sys.executable,str(TOOLS/f"radio_daily_{name}.py"),"--help"],
                                      capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn("--baseline-sha256",result.stdout)

if __name__=="__main__":
    unittest.main()
