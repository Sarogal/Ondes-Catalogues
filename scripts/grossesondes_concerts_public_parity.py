"""Run the public-safe share of the original Concerts regression tests.

Approval-integrity tests intentionally rely on private approved.json. Their
fixtures must NEVER be uploaded to a public branch, PR job, artifact or logs.
All other test modules are executed unchanged, without network or credentials.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "automation" / "concerts"
DATA_FILE = ROOT / "approved.json"


def main() -> int:
    if DATA_FILE.exists():
        raise SystemExit("Private approval data must not exist in public CI")
    sys.path.insert(0, str(ROOT))
    selected, protected = [], []
    for path in sorted(ROOT.glob("test_*.py")):
        contents = path.read_text(encoding="utf-8")
        if "approved.json" in contents:
            protected.append(path.name)
        else:
            selected.append(path.stem)
    if len(selected) < 45 or len(protected) < 20:
        raise SystemExit("Unexpected regression-test partition: review required")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(m) for m in selected)
    print(f"Public test modules: {len(selected)}; private-only modules: {len(protected)}", flush=True)
    print("Private-only modules are retained in Git and excluded from public execution.", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(f"Executed public-safe cases: {result.testsRun}", flush=True)
    return 0 if result.wasSuccessful() and result.testsRun >= 250 else 1


if __name__ == "__main__":
    raise SystemExit(main())
