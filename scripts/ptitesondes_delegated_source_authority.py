"""First-party organizer website attested by a separate DILA municipal page.

No organizer/domain/city/venue allowlist. The incoming OpenAgenda event, a
website's legal notice, and an organizer-supplied URL may suggest research
leads but can NEVER mint this proof. A real municipal document must actually
name the venue and reference the nonmunicipal site in the same visible block.
This authenticates ONE website host for ONE venue, not event sessions, public
attendance, commercial reuse or GPS.
"""
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit
import re

from proof import norm
from ptitesondes_dila_municipal_domains import (
    _host, approved_municipal_page_host,
)
from ptitesondes_openagenda_v2_organizer_bridge import FORBIDDEN_HOSTS

_MAX_HTML = 350_000
_MAX_NODES = 3500
_MAX_AGE_DAYS = 30
_SEAL = object()
HIDDEN = frozenset(("script", "style", "noscript", "template",
                    "svg", "iframe", "nav", "footer"))


class DelegatedSourceHostProof:
    __slots__ = ("city", "venue", "host", "official_reference",
                 "checked_on", "_seal")

    def __init__(self, city, venue, host, official_reference, checked_on, seal):
        if seal is not _SEAL:
            raise ValueError("source_authority_requires_official_mint")
        object.__setattr__(self, "city", city)
        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "official_reference", official_reference)
        object.__setattr__(self, "checked_on", checked_on)
        object.__setattr__(self, "_seal", seal)

    def __setattr__(self, name, value):
        raise AttributeError("source_authority_immutable")

    def __delattr__(self, name):
        raise AttributeError("source_authority_immutable")


class _VisibleSections(HTMLParser):
    """Only independent visible article blocks, or content outside articles."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = 0
        self.stack = []
        self.main_depth = 0
        self.article_depth = 0
        self.main_parts = []
        self.article_parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            raise ValueError("municipal_page_too_many_nodes")
        upper = self.stack[-1][1] if self.stack else False
        data = dict(attrs)
        hidden = bool(
            upper or tag in HIDDEN or "hidden" in data
            or str(data.get("aria-hidden") or "").lower() == "true"
            or re.search(
                r"display\s*:\s*none|visibility\s*:\s*hidden",
                str(data.get("style") or "").lower()) is not None)
        self.stack.append((tag, hidden))
        if not hidden and tag == "main":
            self.main_depth += 1
        if not hidden and tag == "article":
            if not self.article_depth:
                self.article_parts = []
            self.article_depth += 1

    def handle_data(self, data):
        if not self.stack or self.stack[-1][1]:
            return
        clean = " ".join(data.split())
        if not clean:
            return
        if self.article_depth:
            if sum(map(len, self.article_parts)) < 22000:
                self.article_parts.append(clean)
        elif self.main_depth:
            if sum(map(len, self.main_parts)) < 22000:
                self.main_parts.append(clean)

    def handle_endtag(self, tag):
        if self.stack and not self.stack[-1][1]:
            if tag == "article" and self.article_depth:
                self.article_depth -= 1
                if self.article_depth == 0:
                    self.blocks.append(" ".join(self.article_parts))
                    self.article_parts = []
            elif tag == "main" and self.main_depth:
                self.main_depth -= 1
                if self.main_depth == 0:
                    self.blocks.append(" ".join(self.main_parts))
                    self.main_parts = []
        for pos in range(len(self.stack) - 1, -1, -1):
            if self.stack[pos][0] == tag:
                del self.stack[pos:]
                break


def _url_host(url):
    if not isinstance(url, str) or not 8 <= len(url) <= 1800:
        return None
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username
                or u.password or u.port not in (None, 443)
                or u.fragment or u.path in ("", "/")):
            return None
        host = _host("https://" + u.hostname + "/")
        if host in FORBIDDEN_HOSTS or host is None:
            return None
        if host.endswith((".openagenda.com", ".opendatasoft.com")):
            return None
        return host
    except ValueError:
        return None


def _same_host(a, b):
    return a.removeprefix("www.") == b.removeprefix("www.")


def mint_delegated_venue_source_proof(
        city, venue, event_url, directory, municipal_reference_url,
        municipal_reference_html, checked_on):
    """Only a DILA-site publication can sponsor a previously unknown host."""
    if (type(checked_on) is not date or not isinstance(city, str)
            or not isinstance(venue, str) or not norm(city) or not norm(venue)
            or not isinstance(municipal_reference_html, str)
            or not 30 <= len(municipal_reference_html) <= _MAX_HTML
            or not isinstance(municipal_reference_url, str)
            or approved_municipal_page_host(
                municipal_reference_url, city, directory) is None):
        return None
    try:
        reference = urlsplit(municipal_reference_url)
        if reference.path in ("", "/") or reference.fragment:
            return None
    except ValueError:
        return None
    host = _url_host(event_url)
    if host is None:
        return None
    # A municipal page cannot grant organizer authority to another municipality,
    # or to itself by simply repeating the event URL. Normal municipal events
    # remain in the original DILA-attested publication path.
    if approved_municipal_page_host(event_url, city, directory) is not None:
        return None
    parser = _VisibleSections()
    try:
        parser.feed(municipal_reference_html)
        parser.close()
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None
    venue_norm = norm(venue)
    host_norm = norm(host)
    for block in parser.blocks:
        body = norm(block)
        # Accept a named venue followed by its published website, or vice
        # versa, only within a single municipal article/main block and near
        # each other. A related venue in another article is NOT an attestation.
        a = re.search(r"(?<![a-z0-9])" + re.escape(venue_norm) +
                      r"(?![a-z0-9])", body)
        if not a:
            continue
        b = re.search(r"(?<![a-z0-9])(?:www )?" +
                      re.escape(host_norm) + r"(?![a-z0-9])", body)
        if b is None or min(abs(a.end()-b.start()),
                            abs(b.end()-a.start())) > 450:
            continue
        return DelegatedSourceHostProof(
            city, venue, host, municipal_reference_url, checked_on, _SEAL)
    return None


def verified_delegated_source(proof, city, venue, event_url, checked_on):
    if (not isinstance(proof, DelegatedSourceHostProof)
            or proof._seal is not _SEAL or type(checked_on) is not date
            or type(proof.checked_on) is not date
            or not 0 <= (checked_on - proof.checked_on).days <= _MAX_AGE_DAYS
            or norm(proof.city) != norm(city)
            or norm(proof.venue) != norm(venue)):
        return False
    host = _url_host(event_url)
    return host is not None and _same_host(proof.host, host)


__all__ = ["DelegatedSourceHostProof",
           "mint_delegated_venue_source_proof",
           "verified_delegated_source"]
