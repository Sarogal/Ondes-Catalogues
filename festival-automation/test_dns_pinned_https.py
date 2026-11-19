"""Offline network-boundary tests: never depend on the public Internet."""
import socket
from unittest import TestCase, mock

from dns_pinned_https import (
    DNSPinnedHTTPSConnection, fetch_public_html,
    resolve_global_ips, safe_public_url,
)


def answers(*addresses):
    result = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        result.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return result


class PinnedOrganizerHTTPSTests(TestCase):
    def test_only_canonical_https_dns_hosts_pass(self):
        self.assertEqual(safe_public_url("https://rockfest.fr/programme"),
                         "https://rockfest.fr/programme")
        for bad in (
            "http://rockfest.fr/", "https://127.0.0.1/",
            "https://[::1]/", "https://169.254.169.254/latest/meta-data/",
            "https://rockfest.fr:443/", "https://person@rockfest.fr/",
            "https://person:pw@rockfest.fr/", "https://rockfest.fr./",
            "https://rockfest.fr.evil.example/", "https://evil.local/",
            "https://localhost/", "https://t.example/",
            "https://rockfest.fr/?x=1", "https://rockfest.fr/#fragment",
            "https://rockfest.fr/\\\\@evil.org/", "https://rockfest.fr/\\nheader",
            "https://rockfest.fr/   ", "https://røckfest.fr/",
            "https://-rockfest.fr/", "https://rockfest.fr.evil.test/",
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(safe_public_url(bad))

    def test_dns_rejects_any_private_or_non_global_answer(self):
        for addr in (
            "127.0.0.1", "10.0.0.5", "172.16.0.3", "192.168.1.1",
            "169.254.169.254", "100.64.0.1", "::1", "fc00::1",
            "fe80::1", "::ffff:127.0.0.1", "2001:db8::1",
            "64:ff9b::7f00:1", "64:ff9b:1::a00:1",
            "2002:c0a8:101::1", "2001:0:c000:201::1",
        ):
            with self.subTest(addr=addr):
                with self.assertRaises(ValueError):
                    resolve_global_ips(
                        "rockfest.fr",
                        resolver=lambda host, port, type: answers("8.8.8.8", addr))
        self.assertEqual(resolve_global_ips(
            "rockfest.fr",
            resolver=lambda host, port, type: answers("8.8.8.8", "1.1.1.1")),
            ["8.8.8.8", "1.1.1.1"])

    def test_host_cannot_trigger_dns_when_invalid(self):
        visited = []
        with self.assertRaises(ValueError):
            resolve_global_ips("localhost", resolver=lambda *args, **kwargs: visited.append(args))
        self.assertEqual(visited, [])

    def test_connect_pins_ip_and_tls_verifies_original_hostname(self):
        conn = DNSPinnedHTTPSConnection("rockfest.fr", timeout=5)
        conn._context = mock.Mock()
        raw = mock.Mock()
        wrapped = mock.Mock()
        conn._context.wrap_socket.return_value = wrapped
        with mock.patch("dns_pinned_https.resolve_global_ips",
                        return_value=["8.8.8.8"]), mock.patch(
                            "dns_pinned_https.socket.create_connection",
                            return_value=raw) as connect:
            conn.connect()
            connect.assert_called_once_with(("8.8.8.8", 443), 5)
            conn._context.wrap_socket.assert_called_once_with(
                raw, server_hostname="rockfest.fr")
            self.assertIs(conn.sock, wrapped)

    def test_no_cross_host_or_downgrade_redirect(self):
        for location in (
            "https://evil.org/steal", "//evil.org/steal",
            "http://rockfest.fr/", "https://127.0.0.1/",
            "https://rockfest.fr@evil.org/", "https://rockfest.fr:8443/",
            "https://rockfest.fr/?redirect=https://evil.org/",
        ):
            with self.subTest(location=location):
                visited = []
                def opener(url):
                    visited.append(url)
                    return 302, {"location": location}, b""
                with self.assertRaises(ValueError):
                    fetch_public_html("https://rockfest.fr/", opener=opener)
                self.assertEqual(visited, ["https://rockfest.fr/"])

    def test_same_host_redirect_then_bounded_html(self):
        seen = []
        def opener(url):
            seen.append(url)
            if url.endswith("/"):
                return 302, {"location": "/festival"}, b""
            return 200, {"content-type":"text/html; charset=UTF-8"}, b"<h1>Festival 2027</h1>"
        self.assertIn("Festival 2027", fetch_public_html(
            "https://rockfest.fr/", opener=opener))
        self.assertEqual(seen, ["https://rockfest.fr/", "https://rockfest.fr/festival"])

    def test_bodies_status_and_content_types_fail_closed(self):
        for status, headers, body in (
            (200, {"content-type": "application/json"}, b'{}'),
            (200, {"content-type": "text/html", "content-encoding": "gzip"}, b"fake"),
            (200, {"content-type": "text/html"}, b"x" * 650_001),
            (204, {"content-type": "text/html"}, b""),
            (200, {"content-type": "text/html; charset=BADENCODING"}, b"text"),
        ):
            with self.subTest(status=status, headers=headers):
                with self.assertRaises(ValueError):
                    fetch_public_html(
                        "https://rockfest.fr/",
                        opener=lambda url: (status, headers, body))


if __name__ == "__main__":
    import unittest
    unittest.main()
