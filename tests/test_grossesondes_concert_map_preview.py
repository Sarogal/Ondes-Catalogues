"""Static regression checks for the public Grosses Ondes concert map preview."""
import json
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/grossesondes/carte-concerts.html"
PUBLIC = ROOT / "docs/grossesondes/concerts.json"

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inline = False
        self.buffers = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and "src" not in dict(attrs):
            self.inline = True
            self.buffers.append("")
    def handle_endtag(self, tag):
        if tag == "script":
            self.inline = False
    def handle_data(self, data):
        if self.inline:
            self.buffers[-1] += data

class ConcertMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.catalogue = json.loads(PUBLIC.read_text(encoding="utf-8"))
    def test_public_map_reads_validated_json_not_private_approvals(self):
        self.assertIn('fetch("./concerts.json"', self.html)
        self.assertNotIn("approved.json", self.html)
        self.assertNotIn("registry.json", self.html)
        self.assertIn("data.schemaVersion!==1", self.html)
        self.assertIn("cache:\"no-store\"", self.html)
        self.assertIn('e.date<start', self.html)
        self.assertIn("isOverseas", self.html)
        self.assertIn("geoPrecision", self.html)
        self.assertIn("safeLink", self.html)
        self.assertNotIn("innerHTML", self.html)
        self.assertNotIn("eval(", self.html)
    def test_catalogue_contains_map_eligible_entries(self):
        catalogue = self.catalogue
        self.assertEqual(catalogue["schemaVersion"], 1)
        venues = {
            v["id"]: v for v in catalogue["venues"]
            if isinstance(v.get("latitude"), (float, int))
            and isinstance(v.get("longitude"), (float, int))
        }
        self.assertGreater(len(venues), 1)
        self.assertGreater(sum(e["venueId"] in venues for e in catalogue["events"]), 1)
    def test_inline_javascript_parses_with_node(self):
        parser = Scripts()
        parser.feed(self.html)
        self.assertEqual(len(parser.buffers), 1)
        self.assertTrue(shutil.which("node"), "Node.js required to check map JS")
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "concert-map.js"
            file.write_text(parser.buffers[0], encoding="utf-8")
            check = subprocess.run(
                ["node", "--check", str(file)], capture_output=True, text=True,
                timeout=20, check=False)
            self.assertEqual(check.returncode, 0, check.stderr)
if __name__ == "__main__":
    unittest.main()
