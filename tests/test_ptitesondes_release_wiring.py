"""Safety of the final public-place release wiring and Pages verification."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from ptitesondes_pages_verify import equivalent

def files():
    return {name:json.loads((ROOT/"docs/ptitesondes"/name).read_text(encoding="utf-8"))
            for name in ("sorties.json","lieux.json")}

class ReleaseWiringTests(unittest.TestCase):
    def test_pages_must_really_match_both_catalogues(self):
        doc=files()
        self.assertTrue(equivalent(doc,deepcopy(doc)))
        changed=deepcopy(doc)
        changed["lieux.json"]["places"]=[]
        self.assertFalse(equivalent(doc,changed))
        changed=deepcopy(doc)
        changed["sorties.json"]["updated_at"]="2000-01-01"
        self.assertFalse(equivalent(doc,changed))

    def test_release_has_opt_in_preview_and_append_only_guard(self):
        wf=(ROOT/".github/workflows/ptitesondes-cloud-sync.yml").read_text(encoding="utf-8")
        self.assertIn("ptitesondes_place_preflight.py --mode preview",wf)
        self.assertIn("ptitesondes_place_preflight.py --mode apply",wf)
        self.assertIn('"$EVENT_NAME" = "workflow_dispatch"',wf)
        self.assertIn('"$USER_MODE" != "publish"',wf)
        self.assertIn("PLACE_RELEASE_CHANGED",wf)
        self.assertIn("docs/ptitesondes/sorties.json docs/ptitesondes/lieux.json",wf)
        self.assertIn("--previous /tmp/ptitesondes-lieux-before-release.json",wf)
        self.assertIn("python scripts/ptitesondes_pages_verify.py",wf)
        self.assertIn("group: ondes-cloud-publication",wf)
        self.assertIn("cancel-in-progress: false",wf)
