"""First-party institutional OpenAgenda ROOT calendar reference, read-only.

One independently approved official website may link directly to an OpenAgenda
agenda root. This corroborates a link between institution and *calendar*; it
does NOT prove calendar ownership, event occurrences, reuse rights, audience,
venue, organizer consent, or authorization to publish. Each event still needs
its own direct OpenAgenda API and evidence checks.

Zero HTTP, credentials, private URLs in public diagnostics, patch or publisher.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_direct_evidence import (
    _calendar_review, SLUG,
)
from ptitesondes_openagenda_v2_geo_bridge import _url
from ptitesondes_openagenda_v2_organizer_index import _VisibleAnchors

SCHEMA = "ptitesondes.oa2.institutional_root_agenda_reference.v1"
MAX_HTML = 500_000
MAX_LINKS = 2400
CUE = re.compile(r"\b(?:agenda|evenements?|programm(?:es?|ation)|calendrier|sorties)\b")
SAFE_REASONS = frozenset((
    "unreviewed_institutional_agenda",
    "institutional_page_unavailable",
    "no_visible_exact_root_link",
    "visible_root_link_observed_not_ownership",
))


def _result(reason="unreviewed_institutional_agenda"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "institutional_root_link_observed": False,
        "independently_attested_owner": False,
        "event_session_verified": False,
        "rights_reviewed": False,
        "age_access_fully_verified": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def _root_link(target, slug):
    """Reject event, share, redirect, locale spoof or parameterized OA URLs."""
    if not isinstance(target, str) or len(target) > 1200:
        return False
    try:
        p = urlsplit(target)
        if (p.scheme != "https" or p.hostname != "openagenda.com"
                or p.port not in (None, 443) or p.username or p.password
                or p.query or p.fragment):
            return False
        path = p.path.strip("/").split("/")
        if path and path[0] in ("fr", "en"):
            path = path[1:]
        return len(path) == 1 and path[0] == slug
    except ValueError:
        return False


def inspect_institutional_agenda_page(reviewed_source, fetched_page):
    """Check exact separately pinned official page visibly links OA ROOT.

    A link to an event on openagenda.com is not proof of delegation of an
    entire agenda; href must be the canonical agenda root. The textual cue
    must be visible on the page, on that exact anchor.
    """
    if (not isinstance(reviewed_source, dict)
            or set(reviewed_source) != {
                "institution_host", "exact_page_url",
                "agenda_slug", "agenda_uid", "timezone"}
            or not isinstance(fetched_page, dict)
            or set(fetched_page) != {"url", "html"}):
        return _result()
    host = reviewed_source.get("institution_host")
    exact_url = reviewed_source.get("exact_page_url")
    reviewed_agenda = {
        k: reviewed_source.get(k)
        for k in ("agenda_slug", "agenda_uid", "timezone")
    }
    if (not isinstance(host, str) or _url(exact_url, host=host) is None
            or not _calendar_review(reviewed_agenda)
            or fetched_page.get("url") != exact_url):
        return _result()
    html = fetched_page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return _result("institutional_page_unavailable")
    parser = _VisibleAnchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return _result("institutional_page_unavailable")
    for target, label in parser.links:
        if (isinstance(label, str) and len(label) <= 500
                and CUE.search(norm_text(label))
                and _root_link(target, reviewed_agenda["agenda_slug"])):
            return dict(
                _result("visible_root_link_observed_not_ownership"),
                institutional_root_link_observed=True,
            )
    return _result("no_visible_exact_root_link")


def redacted_agenda_reference(result):
    """Do not expose institution, URL, slug, UID or arbitrary input reasons."""
    reason = result.get("reason") if isinstance(result, dict) else None
    return {
        "schema": SCHEMA,
        "reason": reason if reason in SAFE_REASONS
                  else "unreviewed_institutional_agenda",
        "contains_private_identifiers": False,
        "institutional_root_link_observed": (
            isinstance(result, dict)
            and result.get("institutional_root_link_observed") is True),
        "independently_attested_owner": False,
        "event_session_verified": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
