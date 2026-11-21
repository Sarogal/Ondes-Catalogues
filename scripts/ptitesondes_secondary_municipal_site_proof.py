"""Authenticate a secondary municipality-operated event domain without any host list.

Authority needs TWO independent live observations:
  * A DILA-attested municipality page explicitly links the candidate host.
  * A legal notice, linked from that host, attributes its publication to the
    same municipality. Neither an OA claim nor the host's own notice alone
    confers authority. Proof is host-scoped, temporary and never proves events,
    venue coordinates, audience or content reuse rights.
"""
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from proof import norm
from ptitesondes_dila_municipal_domains import (
    _host, approved_municipal_page_host,
)

_MAX_HTML = 350_000
_SEAL = object()
_IGNORED = frozenset(("script", "style", "noscript", "template", "svg", "iframe"))
_NON_CONTENT = frozenset(("header", "footer", "nav"))


class SecondaryMunicipalHostProof:
    __slots__ = ("city", "host", "municipal_reference", "checked_on", "_seal")

    def __init__(self, city, host, municipal_reference, checked_on, seal):
        if seal is not _SEAL:
            raise ValueError("secondary_municipal_proof_must_be_independently_minted")
        object.__setattr__(self, "city", city)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "municipal_reference", municipal_reference)
        object.__setattr__(self, "checked_on", checked_on)
        object.__setattr__(self, "_seal", seal)

    def __setattr__(self, name, value):
        raise AttributeError("immutable_secondary_municipal_proof")

    def __delattr__(self, name):
        raise AttributeError("immutable_secondary_municipal_proof")


class _VisibleHTML(HTMLParser):
    """Link destinations must come from actual visible HTML anchors."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []
        self.content = []
        self.active = None
        self.count = 0

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 3500:
            raise ValueError("secondary_proof_html_too_complex")
        data = dict(attrs)
        blocked = ((self.stack and self.stack[-1][1])
                   or tag in _IGNORED or "hidden" in data
                   or str(data.get("aria-hidden", "")).lower() == "true"
                   or "display:none" in str(data.get("style", "")).replace(" ", "").lower())
        self.stack.append((tag, bool(blocked)))
        if tag == "a" and not blocked and self.active is None:
            self.active = [data.get("href"), [], self._in_content()]

    def _in_content(self):
        if not self.stack or self.stack[-1][1]:
            return False
        tags = [t for t, blocked in self.stack if not blocked]
        return (any(t in ("main", "article") for t in tags)
                and not any(t in _NON_CONTENT for t in tags))

    def handle_data(self, value):
        if not self.stack or self.stack[-1][1]:
            return
        if self._in_content() and sum(map(len, self.content)) < 30000:
            self.content.append(value)
        if self.active is not None and sum(map(len, self.active[1])) < 2000:
            self.active[1].append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None:
            self.links.append((self.active[0],
                               " ".join(self.active[1]), self.active[2]))
            self.active = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _parsed(html):
    if not isinstance(html, str) or not 30 <= len(html) <= _MAX_HTML:
        return None
    parser = _VisibleHTML()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None
    return parser


def _exact_host_url(url, host):
    """No redirects, userinfo, arbitrary suffix, query-only or IP shortcuts."""
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https" and parsed.hostname == host
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
            and parsed.path not in ("", "/")
            and _host(url) == host)
    except (ValueError, TypeError):
        return False


def _host_linked_on_municipal_page(reference_url, html, host, city):
    doc = _parsed(html)
    if doc is None:
        return False
    visible = norm(" ".join(doc.content))
    if not (norm("ville de " + city) in visible
            or norm("mairie de " + city) in visible
            or norm("commune de " + city) in visible):
        return False
    for href, _label, inside_content in doc.links:
        if not inside_content or not isinstance(href, str):
            continue
        url = urljoin(reference_url, href)
        if (_host(url) == host and _exact_host_url(url, host)):
            return True
        # A municipality may link to the SECONDARY site's home page.
        try:
            p = urlsplit(url)
            if (p.scheme == "https" and p.hostname == host
                    and p.username is None and p.password is None
                    and p.port in (None, 443) and not p.fragment
                    and _host(url) == host):
                return True
        except ValueError:
            continue
    return False


def _legal_link_from_event(event_url, html, host):
    doc = _parsed(html)
    if doc is None:
        return None
    for href, label, _main in doc.links:
        if not isinstance(href, str):
            continue
        if "mentions legales" not in norm(label + " " + href):
            continue
        legal = urljoin(event_url, href)
        if _exact_host_url(legal, host):
            return legal
    return None


def _legal_editor_claim(legal_html, city, host):
    doc = _parsed(legal_html)
    if doc is None:
        return False
    text = norm(" ".join(doc.content))
    # Exact named host + explicit public-entity editorial ownership,
    # not just a copyright footer or a logo referring to the municipality.
    host_text = norm(host)
    return any(
        norm("le site " + host_text + " est " + verb + " par " + org + city) in text
        for verb in ("edite", "publie", "administre")
        for org in ("la ville de ", "la mairie de ", "la commune de ")
    )


def mint_secondary_municipal_host_proof(
        city, event_url, directory, municipal_reference_url,
        municipal_reference_html, checked_on, *, reader):
    """Live proof for ONE formerly unknown host; no inferred parent domain."""
    if (type(checked_on) is not date or not isinstance(city, str)
            or not norm(city) or not callable(reader)
            or not isinstance(municipal_reference_url, str)
            or approved_municipal_page_host(
                municipal_reference_url, city, directory) is None):
        return None
    # A bare municipal home page is not a specific endorsement page.
    # This also prevents an untrusted caller from supplying a homepage URL
    # together with unrelated HTML claiming a link was present there.
    try:
        ref = urlsplit(municipal_reference_url)
        if ref.path in ("", "/") or ref.fragment:
            return None
    except ValueError:
        return None
    host = _host(event_url)
    if (host is None or not _exact_host_url(event_url, host)
            or approved_municipal_page_host(
                event_url, city, directory) is not None
            or not _host_linked_on_municipal_page(
                municipal_reference_url, municipal_reference_html,
                host, city)):
        return None
    try:
        event_html = reader(event_url)
        legal_url = _legal_link_from_event(event_url, event_html, host)
        if legal_url is None:
            return None
        legal_html = reader(legal_url)
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        return None
    if not _legal_editor_claim(legal_html, city, host):
        return None
    return SecondaryMunicipalHostProof(
        city, host, municipal_reference_url, checked_on, _SEAL)


def verified_secondary_municipal_host(proof, city, event_url, today):
    return bool(
        isinstance(proof, SecondaryMunicipalHostProof)
        and proof._seal is _SEAL and type(today) is date
        and isinstance(city, str) and norm(city) == norm(proof.city)
        and proof.checked_on <= today <= proof.checked_on + timedelta(days=30)
        and _exact_host_url(event_url, proof.host))
