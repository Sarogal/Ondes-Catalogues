import json
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_place_agenda_watch import (
    run_watch, event_leads, safe_url, validate_config, STATE,
)


def fixture():
    catalogue = json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "scripts/ptitesondes_place_agenda_sources.json").read_text(encoding="utf-8"))
    return registry, catalogue


def page(name="mille formes", extra=""):
    return '<html><header>Navigation</header><main><h1>' + name + '</h1>' + extra + '</main></html>'


class VenueAgendaWatchTests(unittest.TestCase):
    def test_registry_is_curated_against_public_places(self):
        registry, catalogue = fixture()
        validate_config(registry, catalogue, None)
        self.assertGreaterEqual(len(registry["sources"]), 4)
        self.assertEqual({s["place_id"] for s in registry["sources"]} -
                         {p["id"] for p in catalogue["places"]}, set())

    def test_initial_watch_then_no_change_then_report_change(self):
        registry, catalogue = fixture()
        registry["sources"] = registry["sources"][:1]
        source = registry["sources"][0]
        get = lambda u: page(extra="<p>Atelier lecture</p>")
        state, report = run_watch(registry, catalogue, getter=get, today=date(2026, 11, 7))
        self.assertTrue(report["sources"][0]["initialized"])
        self.assertFalse(report["sources"][0]["changed"])
        again, report2 = run_watch(registry, catalogue, state, getter=get, today=date(2026, 11, 8))
        self.assertEqual(state, again)
        self.assertEqual(report2["changes"], [])
        newer, report3 = run_watch(
            registry, catalogue, state, getter=lambda u: page(extra="<p>Nouvel atelier daté</p>"),
            today=date(2026, 11, 8))
        self.assertNotEqual(newer, state)
        self.assertEqual(report3["changes"][0]["reason"], "official_page_changed")
        self.assertEqual(report3["event_candidates"], [])

    def test_dated_jsonld_candidate_never_published(self):
        source = fixture()[0]["sources"][0]
        event = {
            "@context": "https://schema.org", "@type": "Event",
            "name": "Éveil artistique pour tout-petits",
            "startDate": "2026-11-19T10:00:00+01:00",
            "endDate": "2026-11-19T10:45:00+01:00",
            "location": {"name": "mille formes Montpellier"},
            "url": source["url"],
        }
        html = page(extra='<script type="application/ld+json">' +
                    json.dumps(event) + '</script>')
        leads = event_leads(html, source, date(2026, 11, 7))
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["status"], "requires_independent_session_proof")
        self.assertNotIn("public_eligible", leads[0])
        self.assertNotIn("date_start", leads[0])

    def test_never_invent_sessions_from_season_or_recurring_opening(self):
        source = fixture()[0]["sources"][0]
        season = {"@type": "Event", "name": "Mille formes saison 2",
                  "startDate": "2026-11-07T09:30:00+01:00",
                  "endDate": "2027-02-21T18:00:00+01:00",
                  "location": {"name": "mille formes Montpellier"},
                  "url": source["url"]}
        html = page(extra="<p>Mercredi 9h30 - 18h</p>" +
                    '<script type="application/ld+json">' +
                    json.dumps(season) + '</script>')
        self.assertEqual(event_leads(html, source, date(2026, 11, 7)), [])

    def test_unknown_venue_external_links_or_missing_time_rejected(self):
        source = fixture()[0]["sources"][0]
        for changes in (
            {"location": {"name": "Le Zénith"}}, {"url": "https://evil.example/event"},
            {"startDate": "2026-11-19"}, {"startDate": "2026-01-01T10:00:00+01:00"},
        ):
            event = {"@type": "Event", "name": "Atelier pour enfants",
                     "startDate": "2026-11-19T10:00:00+01:00",
                     "location": {"name": "mille formes Montpellier"},
                     "url": source["url"]}
            event.update(changes)
            html = '<script type="application/ld+json">' + json.dumps(event) + '</script>'
            with self.subTest(changes=changes):
                self.assertEqual(event_leads(html, source, date(2026, 11, 7)), [])

    def test_failure_keeps_previous_fingerprint(self):
        registry, catalogue = fixture()
        registry["sources"] = registry["sources"][:1]
        source = registry["sources"][0]
        old = {"schema": STATE, "fingerprints": {source["id"]: "a" * 64}}
        state, report = run_watch(
            registry, catalogue, old, getter=lambda u: "<html>Page sans identité</html>",
            today=date(2026, 11, 7))
        self.assertEqual(state, old)
        self.assertEqual(report["sources"][0]["status"], "source_unavailable")
        self.assertEqual(report["changes"], [])

    def test_refuse_unsafe_urls_and_unregistered_place(self):
        for url in ("http://www.montpellier.fr/events", "https://localhost/a",
                    "https://www.montpellier.fr@127.0.0.1/a",
                    "https://www.montpellier.fr:1234/a",
                    "https://www.montpellier.fr/a?q=secret",
                    "https://unknown.org/programme",
                    "https://www.montpellier.fr/a#fragment"):
            with self.subTest(url=url):
                self.assertFalse(safe_url(url))
        registry, catalogue = fixture()
        registry["sources"][0]["place_id"] = "faux-lieu"
        with self.assertRaises(ValueError):
            validate_config(registry, catalogue, None)


if __name__ == "__main__":
    unittest.main()
