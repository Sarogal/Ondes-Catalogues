"""HTTPS fetch for newly discovered, untrusted organizer-domain *research*.

This module is intentionally separate from the code-reviewed institutional
source fetcher. Every DNS answer is checked before a TCP connection, then the
actual connection is made to that exact approved IP (no second DNS lookup).
TLS still validates the original hostname via SNI and the certificate.
Proxy environment variables are ignored. Redirects never change host.
"""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

MAX_HTML = 650_000
MAX_URL = 1500
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".test",
                    ".invalid", ".example", ".onion", ".lan", ".home", ".arpa")
# IPv4 embedded in globally addressed IPv6 can still reach internal IPv4
# networks through NAT64, 6to4 or Teredo. Fail closed on those prefixes.
EMBEDDED_IPV4_NETWORKS = tuple(ipaddress.ip_network(prefix) for prefix in (
    "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32",
))

HOST_PATTERN = re.compile(
    r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
)


def safe_public_url(value):
    """Canonical HTTPS URL, without userinfo, IP literal, query or fragments."""
    if (not isinstance(value, str) or not 12 <= len(value) <= MAX_URL
            or any(ord(c) < 33 or ord(c) == 127 for c in value)
            or "\\" in value):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port is not None
                or parts.query or parts.fragment or parts.netloc.lower() != host
                or not host.isascii() or host.endswith(BLOCKED_SUFFIXES)
                or HOST_PATTERN.fullmatch(host) is None):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        return value
    except (ValueError, TypeError, UnicodeError):
        return None


def resolve_global_ips(host, *, resolver=None):
    """Reject the entire DNS set if even one answer is not global."""
    if (not isinstance(host, str)
            or safe_public_url("https://" + host + "/") is None):
        raise ValueError("Unsafe host")
    resolve = resolver if resolver is not None else socket.getaddrinfo
    answers = resolve(host, 443, type=socket.SOCK_STREAM)
    if not answers or len(answers) > 32:
        raise ValueError("DNS answer absent or excessive")
    public = []
    for family, kind, _protocol, _canon, address in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise ValueError("Unexpected DNS socket family")
        address_string = address[0]
        ip = ipaddress.ip_address(address_string)
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            raise ValueError("IPv4-mapped address forbidden")
        if (not ip.is_global or ip.is_multicast or ip.is_reserved
                or (ip.version == 6 and any(
                    ip in prefix for prefix in EMBEDDED_IPV4_NETWORKS))):
            raise ValueError("Non-global or IPv4-embedded DNS address")
        literal = str(ip)
        if literal not in public:
            public.append(literal)
    return public


class DNSPinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated numeric IP; authenticate the HTTPS domain."""
    def connect(self):
        last = None
        for address in resolve_global_ips(self.host):
            raw = None
            try:
                raw = socket.create_connection((address, self.port), self.timeout)
                self.sock = self._context.wrap_socket(
                    raw, server_hostname=self.host)
                return
            except (OSError, ssl.SSLError) as exc:
                if raw is not None:
                    raw.close()
                last = exc
        raise OSError("No validated HTTPS endpoint reachable") from last


def _one_request(url):
    parts = urlsplit(url)
    conn = DNSPinnedHTTPSConnection(
        parts.hostname, port=443, timeout=10,
        context=ssl.create_default_context())
    try:
        conn.request(
            "GET", parts.path or "/",
            headers={"User-Agent": "GrossesOndesOrganizerDomainResearch/1.0",
                     "Accept": "text/html,application/xhtml+xml",
                     "Accept-Encoding": "identity"})
        response = conn.getresponse()
        # Bounded even on errors/redirects. Never log the body or URL.
        body = response.read(MAX_HTML + 1)
        if len(body) > MAX_HTML:
            raise ValueError("Unbounded HTML body")
        headers = {k.lower(): v for k, v in response.getheaders()}
        return response.status, headers, body
    finally:
        conn.close()


def fetch_public_html(url, *, opener=None, max_redirects=2):
    """Fetch a novel organizer page after fresh DNS/IP/TLS verification.

    Redirects are resolved relative to the previous *validated* URL, and
    must remain on the exact hostname. The internal opener is only injectable
    for offline tests; production always uses DNSPinnedHTTPSConnection.
    """
    origin = safe_public_url(url)
    if origin is None or type(max_redirects) is not int or not 0 <= max_redirects <= 2:
        raise ValueError("Untrusted candidate URL")
    base_host = urlsplit(origin).hostname
    read = _one_request if opener is None else opener
    current = origin
    for hop in range(max_redirects + 1):
        status, headers, body = read(current)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("location")
            if not isinstance(location, str) or hop == max_redirects:
                raise ValueError("Forbidden or excessive redirect")
            next_url = urljoin(current, location)
            if (safe_public_url(next_url) is None
                    or urlsplit(next_url).hostname != base_host):
                raise ValueError("Redirect left original HTTPS host")
            current = next_url
            continue
        if status != 200:
            raise ValueError("HTTPS response not successful")
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("Compressed HTML not allowed")
        mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in ("text/html", "application/xhtml+xml"):
            raise ValueError("Non-HTML response")
        if not isinstance(body, bytes) or len(body) > MAX_HTML:
            raise ValueError("Invalid bounded HTML body")
        charset_match = re.search(r"charset\s*=\s*([a-zA-Z0-9_-]+)",
                                  headers.get("content-type", ""), re.I)
        charset = charset_match.group(1) if charset_match else "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except LookupError as exc:
            raise ValueError("Unknown HTML encoding") from exc
    raise ValueError("Redirect budget exhausted")
