"""Open-world PRIVATE discovery of source links from DILA-backed municipal pages.

An independently authenticated municipal web page may mention a previously
unknown theatre, organizer, calendar, ticketing site or cultural domain.
Those URLs become research leads, NEVER official, approved or publishable
sources. No destination URL is fetched here; SSRF, DNS rebinding and source
ownership are separate, mandatory future admission checks.

No source/city/venue/organizer/category/wording/domain allowlist. The DILA
directory validates only the *municipal page's* own origin, not its links.
No Git writes, no public catalogue access, no scheduler, no publisher bridge.
"""
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import re
from urllib.parse import urljoin, urlsplit

from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_municipal_official_page_reader import MunicipalOfficialPageReader

SCHEMA = "ptitesondes.dynamic_municipal_source_links_research.v1"
MAX_HTML = 450_000
MAX_PAGE_LINKS = 3000
MAX_BATCH = 40
MAX_URL = 1000
MAX_QUERY = 400
DNS_LABELS = re.compile(
    r"(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+\Z"
)
NONPUBLIC_SUFFIXES = (".local", ".localhost", ".internal", ".test", ".invalid")
REPORT_STATUSES = frozenset({
    "unverified_municipal_source", "municipal_page_html_invalid",
    "municipal_page_needs_partition", "municipal_source_cursor_mismatch",
    "private_source_link_research_only", "invalid_private_municipal_reader",
    "municipal_page_unavailable",
})


class _VisiblePageLinks(HTMLParser):
    """All visible HTML links, regardless of page structure or event wording.

    Older municipal sites use arbitrary wrappers, not <main>/<article>.
    Discovery must not discard their URLs for lack of a preferred HTML tag.
    Hidden/script/template URLs are not rendered links, so they are excluded.
    """
    NON_RENDERED = frozenset({
        "script", "style", "noscript", "template", "iframe", "svg", "head",
    })
    VOID = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ancestors = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if len(self.ancestors) > 100:
            raise ValueError("municipal_html_depth_exceeded")
        props = dict(attrs)
        style = str(props.get("style") or "").lower().replace(" ", "")
        prior_hidden = self.ancestors[-1][1] if self.ancestors else False
        hidden = (prior_hidden or tag in self.NON_RENDERED
                  or "hidden" in props or props.get("aria-hidden") == "true"
                  or "display:none" in style or "visibility:hidden" in style)
        if tag == "a" and not hidden:
            self.links.append(props.get("href"))
        if tag not in self.VOID:
            self.ancestors.append((tag, hidden))

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            for idx in range(len(self.ancestors) - 1, -1, -1):
                if self.ancestors[idx][0] == tag:
                    del self.ancestors[idx:]
                    break


def _safe_url(raw, *, base=None):
    """Shape-only guard. This DOES NOT authorize a subsequent HTTP request."""
    if (type(raw) is not str or not raw or len(raw) > MAX_URL
            or re.search(r"[\x00-\x20\x7f\\]", raw)
            or raw.startswith("//")):
        return None
    # Ordinary municipal pages frequently use bare relative hrefs such
    # as "agenda/jeunesse" or "sorties.html", not only /, ./ and ../.
    # Scheme-bearing payloads (javascript:, data:, http:) must never be
    # rewritten into seemingly harmless HTTPS paths.
    try:
        relative = urlsplit(raw)
        if not relative.scheme and not relative.netloc:
            if not isinstance(base, str) or not _safe_url(base):
                return None
            raw = urljoin(base, raw)
        u = urlsplit(raw)
        host = u.hostname
        if (u.scheme != "https" or host is None or u.username
                or u.password or u.port not in (None, 443)
                or not DNS_LABELS.fullmatch(host)
                or host.endswith(NONPUBLIC_SUFFIXES)
                or u.fragment or len(u.query) > MAX_QUERY
                or u.path.startswith("//")
                or len(raw) > MAX_URL):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        # URL parsing can accept unsafe component delimiters which may have
        # alternate interpretations across later transport implementations.
        if "%" in u.netloc or "@" in u.netloc:
            return None
        return raw
    except (TypeError, ValueError):
        return None


def _blank(status):
    return {
        "schema": SCHEMA, "status": status, "source_candidates": [],
        "source_candidates_this_batch": 0,
        "total_links_on_page": 0, "next_cursor": None,
        "municipal_domain_confirmed_by_dila": False,
        "candidate_domains_officially_approved": False,
        "organizers_independently_verified": False,
        "event_sessions_verified": False, "reuse_rights_verified": False,
        "geography_verified": False, "publisher_connected": False,
        "publication_ready": False, "approval_granted": False,
        "public_writes": 0, "discovered_destination_fetches": 0,
    }


def scan_municipal_page(city, dila_directory, page, *, cursor=None,
                        batch_size=MAX_BATCH):
    """Discover any visible HTTPS link, not just familiar event vocabulary.

    The caller must fetch DILA and the municipal HTML independently, with
    pinned HTTPS origins, no redirects and bounded reads. Both inputs are
    re-checked here; links are only PRIVATE candidates. Each result's cursor
    binds to the exact HTML hash to prevent silent skipping after page changes.
    """
    empty = _blank("unverified_municipal_source")
    if (type(city) is not str or not city.strip()
            or type(page) is not dict or set(page) != {"url", "html"}
            or type(page.get("html")) is not str
            or not 0 < len(page["html"].encode("utf-8")) <= MAX_HTML
            or type(batch_size) is not int
            or not 1 <= batch_size <= MAX_BATCH):
        return empty
    page_url = _safe_url(page.get("url"))
    if not page_url:
        return empty
    authority_host = approved_municipal_page_host(
        page_url, city, dila_directory)
    if authority_host is None or authority_host != urlsplit(page_url).hostname:
        return empty

    parser = _VisiblePageLinks()
    try:
        parser.feed(page["html"])
        parser.close()
    except (ValueError, TypeError):
        return _blank("municipal_page_html_invalid")
    if len(parser.links) > MAX_PAGE_LINKS:
        # Never silently drop an unexamined tail of links.
        return _blank("municipal_page_needs_partition")
    seen, candidates = set(), []
    for href in parser.links:
        url = _safe_url(href, base=page_url)
        if url is None or url == page_url or url in seen:
            continue
        seen.add(url)
        # No request to discovered URL. Not a claim that its owner exists.
        candidates.append(url)

    digest = sha256(page["html"].encode("utf-8")).hexdigest()
    offset = 0
    if cursor is not None:
        if (type(cursor) is not dict
                or set(cursor) != {"page_sha256", "next_index"}
                or cursor["page_sha256"] != digest
                or type(cursor["next_index"]) is not int
                or not 0 < cursor["next_index"] < len(candidates)):
            return _blank("municipal_source_cursor_mismatch")
        offset = cursor["next_index"]
    selection = candidates[offset:offset + batch_size]
    next_index = offset + len(selection)
    next_cursor = ({"page_sha256": digest, "next_index": next_index}
                   if next_index < len(candidates) else None)
    return {
        **_blank("private_source_link_research_only"),
        "source_candidates": [
            {"url": url,
             "provenance": "visible_link_from_dila_correlated_municipal_page",
             "source_ownership_unverified": True, "publication_ready": False}
            for url in selection
        ],
        "source_candidates_this_batch": len(selection),
        "total_links_on_page": len(candidates),
        "next_cursor": next_cursor,
        "municipal_domain_confirmed_by_dila": True,
    }


def research_from_private_municipal_reader(group, reader, *, cursor=None,
                                           batch_size=MAX_BATCH):
    """Opt-in adapter to the EXISTING OA+DILA municipal venue page reader.

    Avoid reconstructing separate OpenAgenda / DILA fetch pipelines. The
    reader selects an exact municipal page, and the DILA record is rechecked.
    No untrusted candidate supplies an official URL pin or a host allowlist.
    """
    if (type(group) is not dict or not isinstance(reader, MunicipalOfficialPageReader)
            or type(group.get("city")) is not str
            or not group["city"].strip()):
        return _blank("invalid_private_municipal_reader")
    try:
        url, html = reader.official_page_get(group)
        if not isinstance(url, str) or not isinstance(html, str):
            return _blank("municipal_page_unavailable")
        dila = reader.dila_directory_get(group["city"])
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("municipal_page_unavailable")
    return scan_municipal_page(
        group["city"], dila, {"url": url, "html": html},
        cursor=cursor, batch_size=batch_size)


def public_redacted_summary(report):
    """Safe aggregate only: never reveal private links, city or place names."""
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("status") not in REPORT_STATUSES
            or type(report.get("source_candidates_this_batch")) is not int
            or not 0 <= report["source_candidates_this_batch"] <= MAX_BATCH
            or (report.get("next_cursor") is not None
                and (type(report["next_cursor"]) is not dict
                     or set(report["next_cursor"]) != {"page_sha256", "next_index"}))):
        raise ValueError("invalid_private_source_research_report")
    return {
        "schema": SCHEMA,
        "status": report["status"],
        "candidates_examined_in_batch": report["source_candidates_this_batch"],
        "has_more": report["next_cursor"] is not None,
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
