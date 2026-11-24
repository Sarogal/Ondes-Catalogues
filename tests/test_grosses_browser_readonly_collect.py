"""Offline contracts for isolated signed-origin browser evidence."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))

from grossesondes_browser_readonly_collect import signed_targets, collect, SCHEMA
from grossesondes_cloud_sync import load_isolated_browser_evidence

HOME = "https://www.mozhell.fr/fr/"
OTHER = "https://festivalgueulesdebois.com/"
HTML = "<main><h1>MozHell Open Air 2027</h1><p>23 au 25 juillet 2027</p></main>"
DAY = "2026-11-24"

def fixtures():
    published = {"schema": 1, "festivals": [
        {"slug": "mozhell-open-air-2027", "officialSite": HOME,
         "startDate": "2027-07-23", "lat": None, "lon": None,
         "showOnMap": False},
        {"slug": "located-2027", "officialSite": OTHER,
         "startDate": "2027-08-19", "lat": 47.0, "lon": 2.0,
         "showOnMap": True},
    ]}
    history = {"schema": 2, "knownFestivals": [
        {"slug": "old-open-air", "officialSite": OTHER, "lastKnownYear": 2026}
    ]}
    return published, history

class IsolatedBrowserCollectionTests(unittest.TestCase):
    def test_only_registered_public_origins_selected(self):
        pub, hist = fixtures()
        sources = signed_targets(pub, hist, date(2026, 11, 24), slot=0)
        self.assertEqual(set(sources), {HOME, OTHER})
        self.assertNotIn("https://evil.example/path", sources)

    def test_failed_network_does_not_serialize_exception_or_html(self):
        urls = [HOME, OTHER]
        def render(url):
            if url == OTHER:
                raise OSError("CREDENTIALS_SHOULD_NOT_LEAK")
            return HTML
        report = collect(urls, renderer=render)
        self.assertEqual(len(report["entries"]), 1)
        self.assertEqual(report["entries"][0]["officialSite"], HOME)
        self.assertNotIn("CREDENTIALS_SHOULD_NOT_LEAK", str(report))
        self.assertEqual(report["entries"][0]["sha256"],
                         sha256(HTML.encode()).hexdigest())

    def test_follows_bounded_same_host_official_ticket_link(self):
        linked = "https://www.mozhell.fr/fr/billetterie"
        home = '<main><a href="/fr/billetterie">Billetterie officielle</a></main>'
        called = []
        def render(url):
            called.append(url)
            return home if url == HOME else HTML
        proof = collect([HOME], renderer=render)
        self.assertEqual(called, [HOME, linked])
        self.assertEqual(len(proof["entries"]), 2)

    def test_reject_unsafe_unsigned_url(self):
        with self.assertRaises(ValueError):
            collect(["http://localhost/"], renderer=lambda _: HTML)

class IsolatedBrowserArtifactTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "evidence.json"
        self.pub, self.history = fixtures()
        self.payload = {"schema": SCHEMA, "date": DAY,
                        "entries": [{"officialSite": HOME, "html": HTML,
                        "sha256": sha256(HTML.encode()).hexdigest()}]}

    def read(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return load_isolated_browser_evidence(
            self.path, self.pub, self.history, DAY)

    def test_same_run_signed_html_verified_by_digest(self):
        self.assertEqual(self.read(), {HOME: HTML})

    def test_tampered_html_cannot_enter_publisher(self):
        self.payload["entries"][0]["html"] = HTML + " <script>fake</script>"
        with self.assertRaises(ValueError):
            self.read()

    def test_unknown_source_cannot_enter_publisher(self):
        self.payload["entries"][0]["officialSite"] = "https://other.example/"
        with self.assertRaises(ValueError):
            self.read()

    def test_cross_day_artifact_cannot_enter_publisher(self):
        self.payload["date"] = "2026-11-23"
        with self.assertRaises(ValueError):
            self.read()

    def test_signed_home_link_may_enter_only_if_actually_discovered(self):
        link = "https://www.mozhell.fr/fr/billetterie"
        homepage = '<main><a href="/fr/billetterie">Billetterie</a></main>'
        self.payload["entries"][0]["html"] = homepage
        self.payload["entries"][0]["sha256"] = sha256(homepage.encode()).hexdigest()
        self.payload["entries"].append({
            "officialSite": link, "html": HTML,
            "sha256": sha256(HTML.encode()).hexdigest()})
        self.assertEqual(self.read()[link], HTML)
        self.payload["entries"][0]["html"] = "<main>aucun lien</main>"
        self.payload["entries"][0]["sha256"] = sha256(
            self.payload["entries"][0]["html"].encode()).hexdigest()
        with self.assertRaises(ValueError):
            self.read()

    def test_missing_browser_artifact_fails_closed(self):
        self.assertEqual(load_isolated_browser_evidence(
            self.path, self.pub, self.history, DAY), {})

if __name__ == "__main__":
    unittest.main()
