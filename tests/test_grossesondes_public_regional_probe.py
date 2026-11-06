"""Offline safeguards for the free public regional probe."""
import sys
from pathlib import Path
from datetime import date, timedelta
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from grossesondes_public_regional_probe import (
    INDEXES, MAX_REQUESTS, inspect_index, selected_indexes, run,
    fetch_index, normalized)


class PublicRegionalProbeTests(unittest.TestCase):
    def test_thirteen_regions_and_fixed_https_sources(self):
        self.assertEqual(len(INDEXES), 18)
        self.assertEqual(len({region for region, _ in INDEXES}), 13)
        self.assertEqual(len({url for _, url in INDEXES}), 18)
        self.assertTrue(all(url.startswith("https://") for _, url in INDEXES))

    def test_visible_labels_only_no_scripts_or_hidden(self):
        html = ("""<main><script><a>Secret Metal Fest 2027</a></script>
          <div hidden><a>Hidden Metal Fest 2027</a></div>
          <div aria-hidden="true"><a>Excluded Metal Fest 2027</a></div>
          <div style="display: none"><a>Invisible Rock Festival</a></div>
          <a href="/safe">Festival Heavy Metal des Cèdres 2027</a>
          <a href="/concert">Concert metal 2027</a>
          <a href="/cinema">Festival cinéma</a></main>""")
        doc = inspect_index(html)
        self.assertEqual(doc["visible_anchor_count"], 3)
        self.assertEqual(doc["themed_visible_label_count"], 1)
        self.assertEqual(doc["confirmed_festivals"], 0)
        self.assertEqual(doc["published"], 0)
        self.assertFalse(doc["linkless_hint"])

    def test_script_only_is_just_uncertain_hint(self):
        doc = inspect_index("<script>const festival = 'Rock Festival 2027'</script>")
        self.assertEqual(doc["visible_anchor_count"], 0)
        self.assertTrue(doc["linkless_hint"])
        self.assertEqual(doc["themed_visible_label_count"], 0)

    def test_never_read_external_urls_as_scrape_targets(self):
        with self.assertRaises(ValueError):
            fetch_index("https://127.0.0.1/admin")
        with self.assertRaises(ValueError):
            fetch_index("https://evil.example/festivals")

    def test_bounded_rotation_covers_eighteen_index_sources(self):
        first = date(2026, 11, 6)
        seen = set()
        for i in range(3):
            day = first + timedelta(days=i)
            for slot in ("morning", "evening"):
                batch = selected_indexes(day, slot)
                self.assertEqual(len(batch), MAX_REQUESTS)
                seen.update(batch)
        self.assertEqual(seen, set(INDEXES))
        for bad in ("night", "", None):
            with self.assertRaises(ValueError):
                selected_indexes(first, bad)

    def test_only_four_requests_and_no_auto_publication(self):
        checked = []
        def fetch(url):
            checked.append(url)
            if len(checked) == 2:
                raise OSError("test failure")
            return ("<article><a href='https://evil.example/'>"
                    "Punk Metal Festival 2027</a></article>")
        r = run(date(2026, 11, 6), "morning", fetch=fetch)
        self.assertEqual(len(checked), MAX_REQUESTS)
        self.assertEqual(r["attempted"], MAX_REQUESTS)
        self.assertEqual(r["accessible"], 3)
        self.assertEqual(r["themed_visible_labels"], 3)
        self.assertEqual(r["configured_sources"], 18)
        self.assertEqual(r["configured_regions"], 13)
        self.assertEqual(r["confirmed_festivals"], 0)
        self.assertEqual(r["published"], 0)
        self.assertIs(r["publication_authorized"], False)
        self.assertTrue(r["review_only"])
        self.assertFalse(any("candidate_url" in x for x in r["rows"]))


if __name__ == "__main__":
    unittest.main()
