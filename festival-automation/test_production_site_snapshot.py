"""Offline safety tests for the read-only Infomaniak source snapshot."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from production_site_snapshot import Stylesheets, same_origin_url


class ProductionSnapshotTests(unittest.TestCase):
    def test_only_https_no_credentials_and_actual_origin(self):
        self.assertTrue(same_origin_url("https://grosses-ondes.fr/app.js"))
        for url in (
            "http://grosses-ondes.fr/app.js",
            "https://grosses-ondes.fr.evil.test/app.js",
            "https://someone@grosses-ondes.fr/app.js",
            "https://other.example/app.js",
            "https://grosses-ondes.fr:8443/app.js",
        ):
            self.assertFalse(same_origin_url(url), url)

    def test_stylesheet_discovery_is_same_origin_only(self):
        parser = Stylesheets()
        parser.feed("""
            <link rel="stylesheet" href="/style.css?v=5">
            <link rel="preload" href="/ignored.css">
            <link rel="stylesheet" href="https://evil.example/a.css">
            <link rel="stylesheet" href="//grosses-ondes.fr/css/map.css">
            <link rel="stylesheet" href="/style.css?v=5">
        """)
        self.assertEqual(parser.urls, [
            "https://grosses-ondes.fr/style.css?v=5",
            "https://grosses-ondes.fr/css/map.css",
        ])


if __name__ == "__main__":
    unittest.main()
