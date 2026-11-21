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

    def test_generic_official_proof_never_follows_a_redirect(self):
        for host in ("larayonne.org", "lemetronum.fr"):
            original = "https://" + host + "/evenement/verified-metal/"
            self.assertIn("official event", self.fetch(original, original))
            for final in (
                "https://other.example/evenement/verified-metal/",
                "https://rockstore.fr/evenement/verified-metal/",
                "https://" + host + "/evenement/other-date/",
                "http://" + host + "/evenement/verified-metal/",
            ):
                with self.subTest(host=host, final=final):
                    with self.assertRaisesRegex(
                            ValueError, "Redirection générique"):
                        self.fetch(original, final)

    def test_every_committed_reviewed_venue_host_is_fetchable(self):
        import generic_music_event
        # Regression: Astrolabe passed the verifier and publisher contracts,
        # but the network boundary omitted its reviewed host.
        self.assertIn("www.lastrolabe.org", generic_music_event.ALLOWED_HOSTS)
        for venue_id, spec in generic_music_event.SPECS.items():
            url = (spec["base"] + spec["eventPathPrefix"].lstrip("/")
                   + "verified-metal/")
            with self.subTest(venue=venue_id, url=url):
                self.assertIn("official event", self.fetch(url, url))

    def test_each_reviewed_host_requires_the_same_exact_event_url(self):
        import generic_music_event
        for venue_id, spec in generic_music_event.SPECS.items():
            url = (spec["base"] + spec["eventPathPrefix"].lstrip("/")
                   + "verified-metal/")
            for target in (
                "https://rockstore.fr/other-event/",
                "https://evil.example/other-event/",
                url.replace("verified-metal/", "different-show/"),
                url.replace("https://", "http://"),
            ):
                with self.subTest(venue=venue_id, redirect=target):
                    with self.assertRaisesRegex(ValueError,
                                                "Redirection générique"):
                        self.fetch(url, target)

    def test_unreviewed_hosts_and_insecure_origins_are_rejected_before_network(self):
        for url in (
            "https://unreviewed-venue.example/concert/test/",
            "https://www.lastrolabe.org.evil.example/agenda/knives/",
            "http://www.lastrolabe.org/agenda/knives/",
            "https://www.lastrolabe.org:8080/agenda/knives/",
        ):
            with self.subTest(url=url), \
                 patch.object(engine.discover, "robots_allow") as robots, \
                 patch.object(engine, "urlopen") as opened:
                with self.assertRaisesRegex(ValueError, "non agréé"):
                    engine.download_official(url, {})
                robots.assert_not_called()
                opened.assert_not_called()

    def test_robots_denial_never_opens_url(self):
        with patch.object(engine.discover, "robots_allow", return_value=False), \
             patch.object(engine, "urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "robots.txt"):
                engine.download_official(
                    "https://rockstore.fr/vulves-assassines-21-mai-2027/", {})
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
