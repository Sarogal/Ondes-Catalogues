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

from grossesondes_browser_readonly_collect import (
    signed_targets, prioritize_unavailable, collect, SCHEMA,
)
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

    def test_already_located_future_editions_also_receive_browser_slots(self):
        pub, hist = fixtures()
        pub["festivals"][0]["lat"] = 46.1
        pub["festivals"][0]["lon"] = 6.1
        pub["festivals"][0]["showOnMap"] = True
        sources = signed_targets(pub, hist, date(2026, 11, 24), slot=1)
        self.assertIn(HOME, sources)
        self.assertIn(OTHER, sources)

    def test_undated_but_officially_announced_future_edition_not_ignored(self):
        pub, hist = fixtures()
        pub["festivals"][0]["startDate"] = None
        sources = signed_targets(pub, hist, date(2026, 11, 24), slot=2)
        self.assertIn(HOME, sources)

    def test_expired_2026_editions_never_exhaust_browser_slots(self):
        pub, hist = fixtures()
        pub["festivals"].append({
            "slug": "expired-festival-2026",
            "officialSite": "https://expired-festival.example/",
            "startDate": "2026-10-04", "lat": None, "lon": None,
            "showOnMap": False})
        targets = signed_targets(pub, hist, date(2026, 11, 24), slot=0)
        self.assertNotIn("https://expired-festival.example/", targets)
        self.assertIn(HOME, targets)

    def test_actual_https_failures_receive_browser_slots_outside_baseline(self):
        pub, hist = fixtures()
        pub["festivals"] = [
            {"slug": f"festival-{i}-2027",
             "name": f"Festival Exemple {i} 2027",
             "officialSite": f"https://festival-exemple-{i}.fr/",
             "startDate": "2027-08-19", "lat": 47.0, "lon": 2.0,
             "showOnMap": True}
            for i in range(14)]
        baseline = signed_targets(pub, hist, date.fromisoformat(DAY), slot=0)
        failed = next(r["officialSite"] for r in pub["festivals"]
                      if r["officialSite"] not in baseline)
        def fetch(url):
            if url == failed:
                raise OSError("HTTP unavailable")
            return HTML
        targets, probed, unavailable = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 0, event_name="push", fetch=fetch)
        self.assertEqual(probed, 14)
        self.assertEqual(unavailable, 1)
        self.assertEqual(targets[0], failed)
        self.assertIn(OTHER, targets)
        self.assertLessEqual(len(targets), 8)
        self.assertEqual(len(targets), len(set(targets)))

    def test_incomplete_linkless_root_can_receive_browser_slot(self):
        pub, hist = fixtures()
        pub["festivals"] = [
            {"slug": f"festival-{i}-2027",
             "officialSite": f"https://festival-exemple-{i}.fr/",
             "startDate": "2027-08-19", "lat": 47.0, "lon": 2.0,
             "showOnMap": True, "bands": 5}
            for i in range(14)]
        baseline = signed_targets(pub, hist, date.fromisoformat(DAY), slot=0)
        candidate = next(row for row in pub["festivals"]
                         if row["officialSite"] not in baseline)
        candidate["bands"] = None
        target = candidate["officialSite"]
        def fetch(url):
            return "<main>Loading</main>" if url == target else (
                '<main><a href="/programmation/">Programme</a></main>')
        targets, probed, unavailable = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 0, event_name="push", fetch=fetch)
        self.assertEqual((probed, unavailable), (14, 0))
        self.assertEqual(targets[0], target)
        self.assertIn(OTHER, targets)
        self.assertLessEqual(len(targets), 8)

    def test_no_https_failure_preserves_original_rotation(self):
        pub, hist = fixtures()
        targets, probed, unavailable = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 1, fetch=lambda url: HTML)
        self.assertEqual(targets, signed_targets(pub, hist, date.fromisoformat(DAY), 1))
        self.assertEqual(probed, 2)
        self.assertEqual(unavailable, 0)

    def test_failure_priority_remains_bounded_and_rotates(self):
        pub, hist = fixtures()
        pub["festivals"] = [
            {"slug": f"festival-{i}-2027",
             "name": f"Festival Exemple {i} 2027",
             "officialSite": f"https://festival-exemple-{i}.fr/",
             "startDate": "2027-08-19", "lat": None, "lon": None,
             "showOnMap": False}
            for i in range(10)]
        def fetch(url):
            raise OSError("HTTP unavailable")
        first, probed, unavailable = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 0, fetch=fetch)
        second, _, _ = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 1, fetch=fetch)
        self.assertEqual(probed, 10)
        self.assertEqual(unavailable, 10)
        self.assertFalse(set(first[:5]) & set(second[:5]))
        self.assertIn(OTHER, first)
        self.assertIn(OTHER, second)
        self.assertLessEqual(len(first), 8)
        self.assertLessEqual(len(second), 8)

    def test_failed_unlocated_roots_get_priority_without_starving_other_roots(self):
        pub, hist = fixtures()
        pub["festivals"] = [
            {"slug": f"festival-{i:02d}-2027",
             "name": f"Festival Exemple {i} 2027",
             "officialSite": f"https://festival-exemple-{i:02d}.fr/",
             "startDate": "2027-08-19",
             "lat": None if i < 6 else 47.0,
             "lon": None if i < 6 else 2.0,
             "showOnMap": i >= 6}
            for i in range(12)]
        missing = {row["officialSite"] for row in pub["festivals"][:6]}
        located = {row["officialSite"] for row in pub["festivals"][6:]}
        def fetch(url):
            raise OSError("HTTP unavailable")
        seen = set()
        for slot in range(3):
            targets, probed, unavailable = prioritize_unavailable(
                pub, hist, date.fromisoformat(DAY), slot,
                event_name="push", fetch=fetch)
            self.assertEqual((probed, unavailable), (12, 12))
            self.assertEqual(len(set(targets[:5]) & missing), 3)
            self.assertEqual(len(set(targets[:5]) & located), 2)
            self.assertEqual(len(targets), len(set(targets)))
            self.assertLessEqual(len(targets), 8)
            self.assertIn(OTHER, targets)
            seen.update(targets[:5])
        self.assertEqual(seen, missing | located)

    def test_repeated_runs_same_half_day_advance_failure_rotation(self):
        pub, hist = fixtures()
        pub["festivals"] = [
            {"slug": f"festival-{i:02d}-2027",
             "officialSite": f"https://festival-exemple-{i:02d}.fr/",
             "startDate": "2027-08-19", "lat": None, "lon": None,
             "showOnMap": False}
            for i in range(10)]
        def fetch(url):
            raise OSError("HTTP unavailable")
        first, probed, unavailable = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 0, event_name="push",
            fetch=fetch, rotation_tick=100)
        second, _, _ = prioritize_unavailable(
            pub, hist, date.fromisoformat(DAY), 0, event_name="push",
            fetch=fetch, rotation_tick=101)
        self.assertEqual((probed, unavailable), (10, 10))
        self.assertFalse(set(first[:5]) & set(second[:5]))
        self.assertIn(OTHER, first)
        self.assertIn(OTHER, second)
        self.assertLessEqual(len(first), 8)
        self.assertLessEqual(len(second), 8)

    def test_browser_diagnostics_only_fixed_categories_and_signed_roots(self):
        from grossesondes_official_browser_probe import BrowserEvidenceError
        diagnostics = []
        def render(url):
            if url == OTHER:
                raise BrowserEvidenceError("invalid_bounded_dom")
            return HTML
        report = collect([HOME, OTHER], renderer=render, diagnostics=diagnostics)
        self.assertEqual(diagnostics, [
            {"url": HOME, "status": "root_rendered", "bytes": len(HTML.encode())},
            {"url": OTHER, "status": "invalid_bounded_dom"}])
        self.assertNotIn("diagnostics", report)
        diagnostics = []
        def secret_failure(url):
            raise OSError("DO_NOT_LOG_PRIVATE_EXCEPTION")
        collect([HOME], renderer=secret_failure, diagnostics=diagnostics)
        self.assertEqual(diagnostics, [{"url": HOME, "status": "network_error"}])
        self.assertNotIn("DO_NOT_LOG", str(diagnostics))
        self.assertEqual(BrowserEvidenceError("private message").reason, "navigation_failed")

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

    def test_large_rendered_dom_preserves_link_provenance_but_raw_limit_stays(self):
        from grossesondes_existing_official_updates import page, linked_pages
        link = "https://www.mozhell.fr/fr/billetterie"
        homepage = ('<script>' + 'x' * 700_000 + '</script>'
                    '<main><a href="/fr/billetterie">Billetterie</a></main>')
        with self.assertRaises(ValueError):
            page(homepage)
        with self.assertRaises(ValueError):
            page("é" * 710_000, rendered=True)
        self.assertEqual(linked_pages(HOME, page(homepage, rendered=True)), [link])
        collected = collect([HOME], renderer=lambda url: homepage if url == HOME else HTML)
        self.assertEqual([x["officialSite"] for x in collected["entries"]], [HOME, link])
        self.payload["entries"] = collected["entries"]
        self.assertEqual(self.read()[link], HTML)

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
