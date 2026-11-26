import unittest
from unittest.mock import patch

from radio_daily_live_evidence import LiveEvidence, EvidenceDeferred


class LiveEvidenceTests(unittest.TestCase):
    @patch("radio_daily_live_evidence.fetch_html")
    def test_exact_endpoint_snapshot_is_reused_and_cannot_be_mutated(self, fetch):
        fetch.side_effect = lambda u: (u, b"official page")
        session = LiveEvidence()
        self.assertEqual(session.fetch("https://a.example/"), ("https://a.example/", b"official page"))
        self.assertEqual(session.fetch("https://a.example/"), ("https://a.example/", b"official page"))
        session.fetch("https://b.example/")
        self.assertEqual(fetch.call_count, 2)

    @patch("radio_daily_live_evidence.fetch_page")
    @patch("radio_daily_live_evidence.resolve_api_mirrors", return_value=["a", "b", "c"])
    def test_directory_is_open_and_bounded(self, mirrors, fetch):
        fetch.return_value = [{"name": "new"}]
        session = LiveEvidence()
        result = session.search("New Radio")
        result[0]["name"] = "tampered"
        self.assertEqual(session.search("New Radio"), [{"name": "new"}])
        fetch.assert_called_once_with(["a", "b"], "name", "New Radio", 0, 100)

    @patch("radio_daily_live_evidence.fetch_html", side_effect=OSError("private URL"))
    def test_failure_is_held_without_leaking_endpoint(self, fetch):
        session = LiveEvidence()
        for _ in range(2):
            with self.assertRaisesRegex(EvidenceDeferred, "^live evidence unavailable$"):
                session.fetch("https://a.example/")
        fetch.assert_called_once()
        self.assertEqual(session.calls, 1)

    @patch("radio_daily_live_evidence.fetch_html", return_value=("https://a.example/", b"x"))
    def test_budget_does_not_repeat_network_or_block_cached_value(self, fetch):
        session = LiveEvidence(max_calls=1)
        session.fetch("https://a.example/")
        session.fetch("https://a.example/")
        with self.assertRaisesRegex(EvidenceDeferred, "call budget"):
            session.fetch("https://b.example/")
        fetch.assert_called_once()

    @patch("radio_daily_live_evidence.fetch_html", return_value=("https://a.example/", b"x"))
    def test_expired_session_refuses_even_cached_evidence(self, fetch):
        now = [0]
        session = LiveEvidence(clock=lambda: now[0], max_seconds=2)
        session.fetch("https://a.example/")
        now[0] = 2
        with self.assertRaisesRegex(EvidenceDeferred, "deadline"):
            session.fetch("https://a.example/")

    @patch("radio_daily_live_evidence.observe_hls", return_value={"verdict": "hls"})
    @patch("radio_daily_live_evidence.observe_url", return_value={"verdict": "icy"})
    @patch("radio_daily_live_evidence.probe_url", return_value={"verdict": "sample"})
    def test_services_do_not_confuse_probe_continuity_or_hls(self, probe, icy, hls):
        session = LiveEvidence()
        url = "https://a.example/"
        self.assertEqual(session.probe(url)["verdict"], "sample")
        self.assertEqual(session.continuity(url)["verdict"], "icy")
        self.assertEqual(session.hls(url)["verdict"], "hls")
        self.assertEqual(session.calls, 3)
        probe.assert_called_once()
        icy.assert_called_once_with(url)
        hls.assert_called_once_with(url)

    def test_new_session_does_not_reuse_prior_cycle(self):
        with patch("radio_daily_live_evidence.fetch_html", return_value=("https://a.example/", b"x")) as fetch:
            LiveEvidence().fetch("https://a.example/")
            LiveEvidence().fetch("https://a.example/")
            self.assertEqual(fetch.call_count, 2)
