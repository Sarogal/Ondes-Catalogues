"""Private recheck of UNKNOWN HTTPS event sources without host allowlists.

A source URL discovered from a DILA-corroborated municipal page may be read
via a pinned, globally routable IP with standard TLS hostname verification.
There are NO redirects, proxies, credentials, IP literals, private networks,
DNS re-resolution during connection, or unbounded HTML responses.

Source contents remain untrusted: even matching title/date DOES NOT prove
ownership, organizer identity, reuse rights, location, access or publication.
This cannot be called by the publisher and never updates HOSTS or manifests.
"""
from datetime import date
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

from proof import norm
from proof_text import Visible, date_forms
from ptitesondes_dynamic_municipal_source_links import _safe_url, SCHEMA as LINK_SCHEMA

SCHEMA = "ptitesondes.unlisted_https_source_recheck_private.v1"
MAX_BYTES = 350_000
MAX_DNS_ADDRESSES = 16
TIMEOUT_SECONDS = 10


class _PinnedHTTPS(http.client.HTTPSConnection):
    """TLS connects ONLY to the already validated IP, with SNI of the host."""
    def __init__(self, host, ip):
        super().__init__(
            host, port=443, timeout=TIMEOUT_SECONDS,
            context=ssl.create_default_context())
        self._pinned_ip = ip

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(
                sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def _dns_public_ips(host, resolver=socket.getaddrinfo):
    """Reject the WHOLE resolution if any record is private or ambiguous."""
    try:
        records = resolver(host, 443, type=socket.SOCK_STREAM)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(records, (list, tuple)) or not records:
        return None
    found = set()
    for record in records:
        try:
            family, kind, _proto, _canonical, address = record
            if family not in (socket.AF_INET, socket.AF_INET6):
                return None
            if kind != socket.SOCK_STREAM or not isinstance(address, tuple):
                return None
            ip = ipaddress.ip_address(address[0])
            if (not ip.is_global or ip.is_multicast or ip.is_link_local
                    or ip.is_unspecified or ip.is_loopback
                    or ip.is_reserved or ip.is_private
                    or (ip.version == 6 and ip.ipv4_mapped is not None)):
                return None
            found.add(str(ip))
        except (ValueError, TypeError, IndexError):
            return None
        if len(found) > MAX_DNS_ADDRESSES:
            return None
    return sorted(found) if found else None


def read_unknown_https(url, *, resolver=socket.getaddrinfo,
                       connection_factory=_PinnedHTTPS):
    """Exact GET of a public-IP-pinned HTTPS endpoint; no implicit redirects.

    Returns private HTML string. Not an approval or independent event proof.
    A caller must select the URL from the independently researched municipal
    link candidates; caller-provided HTML is never sufficient for publication.
    """
    if not _safe_url(url):
        raise ValueError("invalid_unlisted_source_url")
    parsed = urlsplit(url)
    ips = _dns_public_ips(parsed.hostname, resolver)
    if not ips:
        raise ValueError("unknown_source_unsafe_dns")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    connection = None
    try:
        # Only a literal globally-routable IP reaches the socket. TLS still
        # verifies the original DNS hostname; no proxy settings are honored.
        connection = connection_factory(parsed.hostname, ips[0])
        connection.request("GET", path, headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity", "Connection": "close",
            "User-Agent": "PtitesOndesPrivateUnlistedSource/1.0",
        })
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("unknown_source_not_200")
        content_type = (response.getheader("Content-Type") or "").split(
            ";", 1)[0].strip().lower()
        if content_type not in ("text/html", "application/xhtml+xml"):
            raise ValueError("unknown_source_invalid_content_type")
        encoding = (response.getheader("Content-Encoding") or "").lower()
        if encoding not in ("", "identity"):
            raise ValueError("unknown_source_compressed_content_rejected")
        size = response.getheader("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > MAX_BYTES):
            raise ValueError("unknown_source_oversized")
        raw = response.read(MAX_BYTES + 1)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("unknown_source_oversized_or_empty")
        return raw.decode("utf-8-sig")
    except (OSError, ValueError, TypeError, UnicodeError, ssl.SSLError,
            http.client.HTTPException):
        # No URLs, headers, exception strings or private candidate data
        # in public logs. Callers only expose stable status codes.
        raise ValueError("unknown_source_fetch_or_validation_failed") from None
    finally:
        if connection is not None:
            connection.close()


def review_private_unlisted_event(link_report, candidate_url, event, *,
                                  reader=read_unknown_https):
    """One source candidate only. Exact title and day are research signals.

    The independently linked page and OpenAgenda may syndicate one another;
    agreement cannot automatically establish organizational independence.
    """
    outcome = {
        "schema": SCHEMA, "status": "source_requires_further_research",
        "title_and_day_visible": False,
        "source_domain_verified_as_organizer": False,
        "independent_event_evidence_established": False,
        "rights_reviewed": False, "geo_verified": False,
        "family_access_verified": False, "publication_ready": False,
        "publisher_connected": False, "public_writes": 0,
    }
    try:
        if (not isinstance(link_report, dict)
                or link_report.get("schema") != LINK_SCHEMA
                or link_report.get("status") != "private_source_link_research_only"
                or link_report.get("municipal_domain_confirmed_by_dila") is not True
                or link_report.get("candidate_domains_officially_approved") is not False
                or not isinstance(link_report.get("source_candidates"), list)
                or not any(type(item) is dict
                           and item.get("url") == candidate_url
                           and item.get("publication_ready") is False
                           and item.get("source_ownership_unverified") is True
                           for item in link_report["source_candidates"])
                or not isinstance(event, dict)
                or type(event.get("title")) is not str
                or not 1 <= len(event["title"]) <= 300
                or type(event.get("date_start")) is not str
                or not _safe_url(candidate_url)):
            return outcome
        target = date.fromisoformat(event["date_start"])
    except (ValueError, TypeError):
        return outcome
    try:
        html = reader(candidate_url)
        if type(html) is not str or len(html.encode("utf-8")) > MAX_BYTES:
            return outcome
        dom = Visible()
        dom.feed(html)
        body = norm(" ".join(dom.words))
        title = norm(event["title"])
        matches = bool(title and title in body and any(
            norm(variant) in body for variant in date_forms(target.isoformat())))
        if matches:
            return dict(outcome, status="same_title_and_day_visible_unverified",
                        title_and_day_visible=True)
        return dict(outcome, status="unmatched_or_missing_public_event_claim")
    except (OSError, ValueError, TypeError, UnicodeError):
        return dict(outcome, status="unlisted_source_unavailable")
