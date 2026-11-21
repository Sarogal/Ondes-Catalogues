"""Independent OpenAgenda -> attributed festival website -> official-edition proof.

OpenAgenda is an *additional* public provenance route, not a closed roster or
an edition authority. Neither private dates nor a private website URL may
authorize publication. The Publisher re-fetches the exact public OpenAgenda
event, derives ONE visible official festival website, then independently
rechecks first-party festival identity, genre and dates over DNS-pinned HTTPS.
All published rows are map-free until a separate geo proof succeeds.
"""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from grossesondes_generic_directory_edition import (
    Heading, verify_official_site_pages,
    private_proposal as directory_proposal,
)
from grossesondes_institutional_edition import slug_for
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS
from source_qualification import Anchors, normalized, classify

PROOF_MODE = "generic-openagenda-first-party-edition.v1"
PRIVATE_NOTES = ("Lien officiel repéré dans une fiche publique OpenAgenda ; "
                 "dates et genre à revérifier. Lieu, artistes et GPS inconnus.")
PUBLISHED_NOTES = ("Site de festival retrouvé dans une fiche OpenAgenda et "
                   "édition revérifiée sur le site officiel ; lieu, artistes "
                   "et coordonnées à confirmer.")
PRIVATE_STATUS = "Attribution OpenAgenda en attente de vérification indépendante"
PUBLISHED_STATUS = "Site et édition revérifiés indépendamment"
PRIVATE_CONFIDENCE = "OpenAgenda (site lié) + site officiel à revérifier"
PUBLISHED_CONFIDENCE = "OpenAgenda (lien recontrôlé) + site officiel (dates)"
OA_PATH = re.compile(r"/(?:[a-z]{2}/)?[a-z0-9-]+/events/[a-z0-9-]+")
SITE_LABELS = frozenset(("site officiel", "site web", "site internet",
                         "site du festival"))
ALLOWED_ROLES = frozenset(("UNKNOWN", "ORGANIZER_CANDIDATE"))


def event_url(url):
    """One real OpenAgenda EVENT on its sole public origin; no path tricks."""
    if not isinstance(url, str) or not 20 <= len(url) <= 500:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "openagenda.com"
                or parsed.query or parsed.fragment
                or OA_PATH.fullmatch(parsed.path) is None):
            return None
    except (TypeError, ValueError):
        return None
    return url if safe_public_url(url) == url else None


def attributed_site(event_html, title, url):
    """One exact visible event h1 + unique labelled festival website root.

    The event platform's URLs, tickets, other events and hidden links are
    never site attribution. Source HTML merely nominates a host; primary
    dates must subsequently be proven on that host independently.
    """
    if (event_url(url) is None or not isinstance(event_html, str)
            or not 0 < len(event_html) <= 650_000
            or not isinstance(title, str)
            or not re.fullmatch(r".{7,150}\s20[2-4][0-9]", title)):
        return None
    heading, anchors = Heading(), Anchors()
    try:
        heading.feed(event_html)
        heading.close()
        anchors.feed(event_html)
        anchors.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    base = normalized(title.rsplit(" ", 1)[0])
    exact = normalized(title)
    if len(base) < 7 or sum(
            x in (base, exact) for x in heading.headings) != 1:
        return None
    # Avoid attributing a site for a different edition via an old OA page.
    from grossesondes_official_html_edition import VisibleText, fold
    visible = VisibleText()
    try:
        visible.feed(event_html)
        visible.close()
        words = " ".join(fold(" ".join(visible.parts)).split())
    except (TypeError, ValueError, UnicodeError):
        return None
    year = title.rsplit(" ", 1)[-1]
    if re.search(r"(?<![0-9])" + re.escape(year) + r"(?![0-9])", words) is None:
        return None
    sites = set()
    for href, label, prefix in anchors.anchors[:500]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        label_key = normalized(label)
        context = normalized(prefix[-180:]) if isinstance(prefix, str) else ""
        role = (label_key in SITE_LABELS or
                ("site officiel" in context and
                 label_key.startswith("www ")))
        if not role or safe_public_url(href) is None:
            continue
        parts = urlsplit(href)
        if (parts.scheme != "https" or parts.username or parts.password
                or parts.port is not None
                or not parts.path.startswith("/")
                or parts.query or parts.fragment
                or parts.hostname == "openagenda.com"
                or classify(href) not in ALLOWED_ROLES):
            continue
        site = "https://" + parts.hostname + "/"
        if safe_public_url(site) == site:
            sites.add(site)
    return next(iter(sites)) if len(sites) == 1 else None


def private_proposal(title, site, dates, today, *, event_ref):
    if event_url(event_ref) is None or slug_for(title) is None:
        return None
    row = directory_proposal(title, site, dates, today)
    if row is None:
        return None
    row.update(
        proofMode=PROOF_MODE, originSlug=event_ref,
        evidence=[event_ref, site],
        notes=PRIVATE_NOTES, verificationStatus=PRIVATE_STATUS,
        sourceConfidence=PRIVATE_CONFIDENCE)
    return row


def validate_private_proposal(row, today):
    if (not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS
            or event_url(row.get("originSlug")) is None
            or row.get("evidence") != [row.get("originSlug"),
                                       row.get("officialSite")]):
        return None
    try:
        verified = date.fromisoformat(row["verified_at"])
        actual = date.fromisoformat(today)
        if actual < verified or (actual - verified).days > 7:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")), row["verified_at"],
        event_ref=row["originSlug"])
    return row if expected == row else None


def validate_verified_row(proposal, row, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE, notes=PUBLISHED_NOTES)
    return row if row == expected else None


def independently_verify(proposal, today, event_fetch=fetch_public_html,
                         organizer_fetch=fetch_public_html):
    """Private hints never pick the official website the Publisher visits."""
    if validate_private_proposal(proposal, today) is None:
        return None
    try:
        html = event_fetch(proposal["originSlug"])
        site = attributed_site(
            html, proposal["name"], proposal["originSlug"])
        if site is None or site != proposal["officialSite"]:
            return None
        root = organizer_fetch(site)
        dates = verify_official_site_pages(
            site, root, proposal["name"],
            int(proposal["name"].rsplit(" ", 1)[-1]), today,
            fetch=organizer_fetch)
    except (OSError, TypeError, ValueError, UnicodeError, KeyError):
        return None
    if dates != (proposal["startDate"], proposal["endDate"]):
        return None
    approved = {key: proposal[key] for key in ROW_KEYS}
    approved.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE, notes=PUBLISHED_NOTES)
    return approved
