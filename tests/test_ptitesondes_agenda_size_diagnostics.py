"""Regressions for oversized official agendas and private diagnostic safety."""
import json
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_place_agenda_watch import fetch, run_watch, MAX_BYTES
from ptitesondes_place_agenda_pace import (
    find_index_hints, MAX_AGENDA_HTML_BYTES, MAX_DETAILS_PER_CYCLE
)


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.body = body
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.body[:limit]


def place_fixture():
    public = json.loads(
        (ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))
    sources = json.loads(
        (ROOT / "scripts/ptitesondes_place_agenda_sources.json").read_text(encoding="utf-8"))
    return public, sources


class SourceSizeTests(unittest.TestCase):
    def test_medium_size_official_html_is_accepted_with_bounded_fetch(self):
        self.assertGreaterEqual(MAX_BYTES, 1_000_000)
        url = "https://www.montpellier.fr/vie-quotidienne/vivre-ici/se-cultiver/jeune-public/mille-formes-centre-dart-pour-les-0-6-ans"
        html = ("<html><main><h1>mille formes</h1>"
                + " " * 410_000 + "</main></html>")
        response = FakeResponse(url, html.encode("utf-8"))
        class FakeOpener:
            def open(self, *args, **kwargs):
                return response
        with patch("ptitesondes_place_agenda_watch.build_opener",
                   return_value=FakeOpener()):
            self.assertEqual(fetch(url), html)

    def test_too_big_html_cannot_be_used(self):
        url = "https://www.montpellier.fr/vie-quotidienne/vivre-ici/se-cultiver/jeune-public/mille-formes-centre-dart-pour-les-0-6-ans"
        class FakeOpener:
            def open(self, *args, **kwargs):
                return FakeResponse(url, b"x" * (MAX_BYTES + 1))
        with patch("ptitesondes_place_agenda_watch.build_opener",
                   return_value=FakeOpener()):
            with self.assertRaisesRegex(ValueError, "Page trop volumineuse"):
                fetch(url)

    def test_pace_big_index_still_finds_child_event_links(self):
        self.assertGreaterEqual(MAX_AGENDA_HTML_BYTES, 1_000_000)
        url = "https://www.ville-pace.bzh/mes-loisirs/agenda/"
        html = ('<main><h1>Agenda Totems</h1><a href="/evenement/bebes-lecteurs/">'
                'Bébés lecteurs</a>' + " " * 520_000 + "</main>")
        urls = find_index_hints(url, html, date(2026, 11, 9))
        self.assertEqual(
            urls, ["https://www.ville-pace.bzh/evenement/bebes-lecteurs/"])
        self.assertEqual(MAX_DETAILS_PER_CYCLE, 6)

    def test_unsupported_or_huge_page_preserves_last_known_fingerprint(self):
        catalogue, registry = place_fixture()
        source = next(s for s in registry["sources"]
                      if s["id"] == "pace-totems-official-agenda")
        registry["sources"] = [source]
        previous = {"schema": "ptitesondes.place_agenda_watch_state.v1",
                    "fingerprints": {source["id"]: "f" * 64}}
        state, report = run_watch(
            registry, catalogue, previous,
            getter=lambda _: ("<html>Totems</html>" + "A" * (MAX_BYTES + 1)),
            today=date(2026, 11, 9))
        self.assertEqual(state, previous)
        self.assertEqual(report["sources"][0]["reason"], "invalid_or_large_html")
        self.assertEqual(report["event_candidates"], [])

    def test_no_raw_failure_message_leaks_to_private_report(self):
        catalogue, registry = place_fixture()
        source = next(s for s in registry["sources"]
                      if s["id"] == "montpellier-mille-formes-programme")
        registry["sources"] = [source]
        secret = "SENSITIVE_STRING_MUST_NOT_APPEAR"
        def get(_):
            raise ValueError(secret)
        state, report = run_watch(registry, catalogue, getter=get,
                                  today=date(2026, 11, 9))
        self.assertEqual(state["fingerprints"], {})
        self.assertEqual(report["sources"][0]["reason"], "validation_failed")
        self.assertNotIn(secret, json.dumps(report))

    def test_individual_identity_failure_is_explicit(self):
        catalogue, registry = place_fixture()
        source = next(s for s in registry["sources"]
                      if s["id"] == "pace-totems-official-agenda")
        registry["sources"] = [source]
        _, report = run_watch(registry, catalogue,
                              getter=lambda _: "<p>Something unrelated</p>",
                              today=date(2026, 11, 9))
        self.assertEqual(report["sources"][0]["reason"], "identity_missing")


if __name__ == "__main__":
    unittest.main()
