"""Offline, adversarial TLS/IP/source checks for unknown organizer domains."""
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_unlisted_source_safe_recheck import (
    _dns_public_ips, read_unknown_https, review_private_unlisted_event,
    SCHEMA, MAX_BYTES,
)
from ptitesondes_dynamic_municipal_source_links import SCHEMA as LINK_SCHEMA

URL = "https://nouveau-conteur-inconnu.fr/spectacles/veillee?id=42"


def dns(*ips):
    entries = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        address = (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443)
        entries.append((family, socket.SOCK_STREAM, 6, "", address))
    return lambda *a, **k: list(entries)


class FakeResponse:
    def __init__(self, html=None, *, status=200, mime="text/html",
                 encoding=None, content_length=None):
        self.status = status
        self.body = (html or "<html><body>hello</body></html>").encode("utf-8")
        self.mime = mime
        self.encoding = encoding
        self.content_length = content_length

    def getheader(self, key):
        return {
            "Content-Type": self.mime,
            "Content-Encoding": self.encoding,
            "Content-Length": self.content_length,
        }.get(key)

    def read(self, max_bytes):
        return self.body[:max_bytes]


class FakeConnection:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []
        self.closed = False

    def request(self, method, path, headers):
        self.calls.append((method, path, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def link_report(url=URL):
    return {
        "schema": LINK_SCHEMA,
        "status": "private_source_link_research_only",
        "municipal_domain_confirmed_by_dila": True,
        "candidate_domains_officially_approved": False,
        "source_candidates": [
            {"url": url, "publication_ready": False,
             "source_ownership_unverified": True}],
    }


class UnlistedSafeSourceTests(unittest.TestCase):
    def test_public_dns_pins_a_literal_address_for_tls_not_an_allowlisted_host(self):
        conn = FakeConnection(FakeResponse(
            "<html><body>Conte musical pour enfants le 5 décembre 2026</body></html>"))
        chosen = []
        def factory(host, ip):
            chosen.append((host, ip))
            return conn
        html = read_unknown_https(URL, resolver=dns("8.8.8.8"),
                                  connection_factory=factory)
        self.assertIn("Conte musical", html)
        self.assertEqual(chosen, [("nouveau-conteur-inconnu.fr", "8.8.8.8")])
        self.assertEqual(len(conn.calls), 1)
        method, path, headers = conn.calls[0]
        self.assertEqual((method, path),
                         ("GET", "/spectacles/veillee?id=42"))
        self.assertEqual(headers["Accept-Encoding"], "identity")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)
        self.assertTrue(conn.closed)

    def test_multiple_global_addresses_are_checked_before_any_connection(self):
        ips = _dns_public_ips("nom-inconnu.fr",
                              dns("2001:4860:4860::8888", "8.8.4.4"))
        self.assertEqual(set(ips), {"2001:4860:4860::8888", "8.8.4.4"})
        blocked = [
            ("8.8.8.8", "127.0.0.1"),
            ("8.8.8.8", "10.0.0.5"),
            ("192.168.1.3",),
            ("169.254.169.254",),
            ("127.0.0.1",),
            ("::1",),
            ("fe80::1",),
            ("224.0.0.1",),
            ("::ffff:127.0.0.1",),
        ]
        for addresses in blocked:
            with self.subTest(addresses=addresses):
                self.assertIsNone(_dns_public_ips("inconnu.fr", dns(*addresses)))

    def test_private_address_rebinding_cannot_be_contacted(self):
        factory = Mock(side_effect=AssertionError("must not connect"))
        with self.assertRaises(ValueError):
            read_unknown_https(URL, resolver=dns("8.8.8.8", "10.8.0.2"),
                               connection_factory=factory)
        factory.assert_not_called()

    def test_redirect_http_error_gzip_and_mime_are_all_holds(self):
        cases = [
            FakeResponse(status=301),
            FakeResponse(status=302),
            FakeResponse(status=404),
            FakeResponse(mime="application/json"),
            FakeResponse(encoding="gzip"),
            FakeResponse(content_length=str(MAX_BYTES + 1)),
            FakeResponse(content_length="infinite"),
            FakeResponse(html="x" * (MAX_BYTES + 1)),
        ]
        for response in cases:
            with self.subTest(code=response.status, mime=response.mime):
                conn = FakeConnection(response)
                with self.assertRaisesRegex(
                        ValueError, "fetch_or_validation_failed"):
                    read_unknown_https(
                        URL, resolver=dns("8.8.8.8"),
                        connection_factory=lambda h, i: conn)
                self.assertEqual(len(conn.calls), 1)
                self.assertTrue(conn.closed)

    def test_invalid_untrusted_urls_never_even_resolve_dns(self):
        resolver = Mock(side_effect=AssertionError("never resolve"))
        invalids = [
            "http://test.fr/a", "https://localhost/", "https://10.0.0.9/",
            "https://127.0.0.1/", "https://test.fr:444/x",
            "https://user:pass@example.fr/", "https://evil.internal/",
            "https://fake.fr.evil.invalid/a", "https://site.fr/#fragment",
            "javascript:alert(1)", "//attacker.fr/",
        ]
        for bad in invalids:
            with self.subTest(url=bad), self.assertRaises(ValueError):
                read_unknown_https(bad, resolver=resolver)
        resolver.assert_not_called()

    def test_source_title_date_match_is_not_officiality_or_publication(self):
        doc = {"title": "Conte musical pour les enfants",
               "date_start": "2026-12-05"}
        html = ("<html><body><h1>Conte musical pour les enfants</h1>"
                "<p>Samedi 5 décembre 2026</p></body></html>")
        outcome = review_private_unlisted_event(
            link_report(), URL, doc, reader=lambda url: html)
        self.assertEqual(outcome["status"],
                         "same_title_and_day_visible_unverified")
        self.assertTrue(outcome["title_and_day_visible"])
        self.assertFalse(outcome["source_domain_verified_as_organizer"])
        self.assertFalse(outcome["independent_event_evidence_established"])
        self.assertFalse(outcome["rights_reviewed"])
        self.assertFalse(outcome["family_access_verified"])
        self.assertFalse(outcome["geo_verified"])
        self.assertFalse(outcome["publication_ready"])
        self.assertFalse(outcome["publisher_connected"])
        self.assertEqual(outcome["public_writes"], 0)
        self.assertNotIn(URL, json.dumps(outcome))

    def test_missing_date_or_title_does_not_claim_corroboration(self):
        doc = {"title": "Conte musical pour les enfants",
               "date_start": "2026-12-05"}
        for html in (
            "<html><h1>Conte musical pour les enfants</h1></html>",
            "<html><p>5 décembre 2026 : hockey enfants</p></html>",
            "<html><script>Conte musical pour les enfants le 5 décembre 2026</script></html>",
        ):
            outcome = review_private_unlisted_event(
                link_report(), URL, doc, reader=lambda url: html)
            self.assertEqual(outcome["status"],
                             "unmatched_or_missing_public_event_claim")
            self.assertFalse(outcome["publication_ready"])

    def test_self_claimed_source_link_or_approval_cannot_enable_recheck(self):
        reader = Mock(side_effect=AssertionError("must not fetch"))
        wrong = [
            dict(link_report(), candidate_domains_officially_approved=True),
            dict(link_report(), municipal_domain_confirmed_by_dila=False),
            dict(link_report(), schema="fake-synthetic"),
            dict(link_report(), source_candidates=[{
                "url": URL, "publication_ready": True,
                "source_ownership_unverified": False}]),
        ]
        for report in wrong:
            outcome = review_private_unlisted_event(
                report, URL, {"title": "Conte", "date_start": "2026-12-05"},
                reader=reader)
            self.assertFalse(outcome["title_and_day_visible"])
            self.assertFalse(outcome["publication_ready"])
        reader.assert_not_called()

    def test_outage_cannot_be_promoted_to_absence_or_confirmation(self):
        def offline(_url):
            raise OSError("contains-private-data-must-not-leak")
        result = review_private_unlisted_event(
            link_report(), URL,
            {"title": "Conte pour enfants", "date_start": "2026-12-05"},
            reader=offline)
        self.assertEqual(result["status"], "unlisted_source_unavailable")
        self.assertNotIn("private", json.dumps(result))
        self.assertFalse(result["publisher_connected"])


if __name__ == "__main__":
    unittest.main()
