"""Network boundary regression: only the official hosts of supported rechecks."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import official_recheck as engine


class Response:
    def __init__(self, url):
        self.url = url
        self.headers = self
    def geturl(self):
        return self.url
    def read(self, limit):
        return b"<html>official event</html>"
    def get_content_charset(self):
        return "utf-8"
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FirstPartyFetchHostTests(unittest.TestCase):
    def fetch(self, original, final):
        with patch.object(engine.discover, "robots_allow", return_value=True), \
             patch.object(engine, "urlopen", return_value=Response(final)):
            return engine.download_official(original, {})

    def test_rockstore_and_laiterie_official_details_are_fetchable(self):
        for url in (
            "https://rockstore.fr/vulves-assassines-21-mai-2027/",
            "https://www.rockstore.fr/vulves-assassines-21-mai-2027/",
            "https://www.artefact.org/la-laiterie/evenements/example-band/",
        ):
            with self.subTest(url=url):
                self.assertIn("official event", self.fetch(url, url))

    def test_redirect_to_other_host_or_http_stays_forbidden(self):
        original = "https://rockstore.fr/vulves-assassines-21-mai-2027/"
        for destination in (
            "https://evil.example/event/",
            "http://rockstore.fr/event/",
            "https://rockstore.fr.evil.example/event/",
            "https://artefact.org/la-laiterie/evenements/test/",
        ):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "Redirection hors domaine"):
                    self.fetch(original, destination)

    def test_robots_denial_never_opens_url(self):
        with patch.object(engine.discover, "robots_allow", return_value=False), \
             patch.object(engine, "urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "robots.txt"):
                engine.download_official(
                    "https://rockstore.fr/vulves-assassines-21-mai-2027/", {})
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
