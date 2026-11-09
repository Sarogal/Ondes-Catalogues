"""Offline tests: missed GitHub crons must not skip national festival source slices."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from official_watch import (
    PAGES, GIT, ORIGIN, choose_sources, choose_pending_rechecks,
    resumable_rotation_tick, run,
)


def sample_catalogue():
    return {
        "schema": 1, "generatedAt": "2026-11-03",
        "festivals": [
            {"slug": f"festival-{i}", "name": f"Festival {i}",
             "officialSite": f"https://fest{i}.example.org/programme",
             "startDate": "2027-06-01"} for i in range(100)
        ],
    }


class ResumeOfficialWatchTests(unittest.TestCase):
    def test_cursor_resumes_missed_calendar_days(self):
        doc = sample_catalogue()
        html = "<html>" + "Festival officiel, programmation et billetterie. " * 10 + "</html>"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            download = lambda url: doc
            first = run(folder, "2026-11-04", limit=6,
                        download_json=download, download_page=lambda url: html)
            state = json.loads((folder / "source-watch-state.json").read_text())
            self.assertEqual(first["rotationTick"], 0)
            self.assertEqual(state["rotation_next_tick"], 1)
            self.assertEqual(len(first["scanned"]), 6)

            # Two full calendar days pass without any successful schedule.
            # The first successful run after the gap MUST take tick 1, not tick 6.
            after_gap = run(folder, "2026-11-07", limit=6,
                            download_json=download, download_page=lambda url: html)
            self.assertEqual(after_gap["rotationTick"], 1)
            self.assertEqual(
                [record["url"] for record in after_gap["scanned"]],
                [url for _, url in choose_sources(doc, date(2026, 11, 7),
                                                   "primary", 6, tick_override=1)],
            )
            self.assertTrue(
                {record["url"] for record in first["scanned"]}.isdisjoint(
                    {record["url"] for record in after_gap["scanned"]}))
            self.assertEqual(json.loads((folder / "source-watch-state.json").read_text())
                             ["rotation_next_tick"], 2)
            self.assertEqual(after_gap["publishedChanges"], 0)

    def test_all_unavailable_sources_do_not_advance_cursor(self):
        doc = sample_catalogue()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "source-watch-state.json").write_text(
                json.dumps({"schema": "grossesondes.source-watch.v1",
                            "sources": {}, "rotation_next_tick": 8}))
            report = run(folder, "2026-11-07", limit=4,
                         download_json=lambda url: doc,
                         download_page=lambda url: (_ for _ in ()).throw(OSError("offline")))
            self.assertEqual(report["rotationTick"], 8)
            self.assertEqual(len(report["unavailable"]), 4)
            self.assertEqual(report["publishedChanges"], 0)
            state = json.loads((folder / "source-watch-state.json").read_text())
            self.assertEqual(state["rotation_next_tick"], 8)

    def test_corrupt_cursor_fails_closed(self):
        for bad in (-1, "2", True, [], {}):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(ValueError, "curseur"):
                    resumable_rotation_tick({"rotation_next_tick": bad},
                                             date(2026, 11, 7), "primary")
                with self.assertRaises(ValueError):
                    choose_sources(sample_catalogue(), date(2026, 11, 7),
                                   tick_override=bad)

    def test_source_priority_remains_bounded_with_cursor(self):
        doc = sample_catalogue()
        target = choose_sources(doc, date(2026, 11, 4), limit=12,
                                tick_override=0)[0][1]
        state = {"future_edition_observations": {
            "future2028": {"source": target, "lastSeen": "2026-11-06"}
        }}
        selection = choose_pending_rechecks(
            doc, date(2026, 11, 7), "primary", 12, state, tick_override=14)
        self.assertEqual(len(selection), 12)
        self.assertEqual(len({url for _, url in selection}), 12)
        self.assertIn(target, {url for _, url in selection})


if __name__ == "__main__":
    unittest.main()
