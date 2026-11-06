"""CDN drift probe reports metadata only; cache buster never approves fields."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from official_watch import GIT, PAGES
from pages_drift_probe import diagnostic


class PagesDriftTests(unittest.TestCase):
    def test_canonical_stale_query_fresh_still_disallows_publication(self):
        seen = []
        def fake(url):
            seen.append(url)
            if url == GIT:
                return {"fingerprint": "abc123", "generatedAt": "2026-11-05",
                        "editions": 124, "noel_officialSite": "https://execution-mgt.fr/"}
            if url == PAGES:
                return {"fingerprint": "old", "generatedAt": "2026-11-03",
                        "editions": 124, "noel_officialSite": None}
            if url == PAGES + "?go_probe=abc123":
                return {"fingerprint": "new", "generatedAt": "2026-11-05",
                        "editions": 124, "noel_officialSite": "https://execution-mgt.fr/"}
            self.fail("unexpected destination")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            found = diagnostic(fetch=fake)
        self.assertEqual(found["pages_canonical"]["generatedAt"], "2026-11-03")
        self.assertEqual(found["pages_diagnostic_query"]["generatedAt"], "2026-11-05")
        self.assertEqual(seen, [GIT, PAGES, PAGES + "?go_probe=abc123"])
        serialized = json.loads(output.getvalue())
        self.assertIs(serialized["safe_to_publish"], False)
        self.assertNotIn("approved", serialized)

    def test_probe_failure_leaves_monitor_in_charge(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            found = diagnostic(fetch=lambda url: (_ for _ in ()).throw(OSError("down")))
        self.assertEqual(found["error"], "OSError")
        self.assertIs(json.loads(output.getvalue())["safe_to_publish"], False)


if __name__ == "__main__":
    unittest.main()
