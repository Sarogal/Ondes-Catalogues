"""Two independent public websites prove an unknown festival and an edition.

A national private candidate may nominate a SAFE HTTPS site. Its claim is
not authoritative. The Publisher independently checks the first-party site,
derives a venue website from a visibly linked first-party practical-info page,
and fetches that venue's PUBLIC event index and event detail. A venue detail
must contain the exact festival name, an edition day inside the claimed
weekend and a direct backlink to the same festival domain. No registered
festival, venue or organizer list; every fetch is DNS-pinned, host-bounded,
limited and independently repeated.

This is append-only and produces no inferred city, venue, artists or map pin.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urljoin, urlsplit
import re

from dns_pinned_https import fetch_public_html, safe_public_url
from grossesondes_generic_directory_edition import verify_official_site_pages
from grossesondes_official_html_edition import VisibleText, fold, explicit_ranges
from grossesondes_institutional_edition import slug_for
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS
from source_qualification import Anchors, normalized, classify

PROOF_MODE = "generic-venue-reciprocal-edition.v1"
PRIVATE_NOTES = ("Site du festival et annonce de salle réciproque à revalider. "
                 "Aucun lieu, artiste ni repère GPS déduit de la source.")
PUBLISHED_NOTES = ("Festival et dates revérifiés sur son site ; événement "
                   "et lien retour indépendamment confirmés par une salle. "
                   "Adresse exacte, artistes et coordonnées à confirmer.")
PRIVATE_STATUS = "Recoupement salle/site en attente du Publisher"
PUBLISHED_STATUS = "Recoupement salle/site revérifié indépendamment"
PRIVATE_CONFIDENCE = "Organisateur + salle liée (observation privée)"
PUBLISHED_CONFIDENCE = "Organisateur + salle (annonce et lien réciproques)"
BLOCKED_FAMILIES = frozenset(("google.com", "google.fr", "facebook.com",
                             "instagram.com", "twitter.com", "x.com",
                             "youtube.com", "linktr.ee", "weezevent.com",
                             "shotgun.live", "helloasso.com", "billetweb.fr"))
MAX_PRIMARY_PAGES = 3   # homepage and two primary same-host info links
MAX_VENUE_ROOTS = 4     # bounded candidate third-party domains
MAX_VENUE_INDEXES = 3   # root + two visible agenda links
MAX_EVENT_PAGES = 3     # at most 3 venue event details
MAX_ANCHORS = 500


def safe_root(url):
    """Only public canonical HTTPS homepage with no query, IP, credentials."""
    if safe_public_url(url) != url:
        return None
    try:
        p = urlsplit(url)
        if (not p.hostname or p.path != "/" or p.query or p.fragment
                or p.port is not None
                or url != "https://" + p.hostname + "/"):
            return None
        return url
    except (ValueError, TypeError):
        return None


def safe_link(href, base, root):
    """No encoded traversal, fragments, queries, redirects or cross-origin."""
    if not isinstance(href, str) or len(href) > 800:
        return None
    try:
        raw = urlsplit(href)
        if ("%" in href or "\\" in href or ".." in raw.path
                or "//" in raw.path or raw.scheme not in ("", "https")
                or raw.query or raw.fragment):
            return None
        target = urljoin(base, href)
        parts = urlsplit(target)
        if (safe_public_url(target) != target
                or parts.hostname != urlsplit(root).hostname
                or parts.path == "/" or len(parts.path) > 320):
            return None
        return target
    except (ValueError, TypeError, UnicodeError):
        return None


def anchor_rows(html):
    if not isinstance(html, str) or not 0 < len(html) <= 650000:
        raise ValueError("Invalid visible-HTML input")
    p = Anchors()
    p.feed(html)
    p.close()
    return p.anchors[:MAX_ANCHORS]


def visible_content(html):
    p = VisibleText()
    p.feed(html)
    p.close()
    return " ".join(fold(" ".join(p.parts)).split())


def _primary_info_pages(site, homepage_html, fetch):
    """Fetch only two same-host links visibly labelled venue or practical info."""
    selected = [(site, homepage_html)]
    possible = []
    for href, label, prefix in anchor_rows(homepage_html):
        key = normalized(str(label) + " " + str(prefix)[-65:])
        if not re.search(r"\b(?:infos? pratiques?|venir|acces|lieu|salle)\b", key):
            continue
        url = safe_link(href, site, site)
        if url is not None and url not in possible:
            possible.append(url)
    for url in possible[:MAX_PRIMARY_PAGES - 1]:
        try:
            selected.append((url, fetch(url)))
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            continue
    return selected


def candidate_venue_roots(site, homepage_html, fetch=fetch_public_html):
    """Find independently verifiable venue hosts, NEVER a sponsor/ticket host.

    First-party practical info must explicitly name a 'lieu'/'salle' and
    the hostname's distinctive token. A random external link is not proof.
    """
    candidates = set()
    for _page_url, page_html in _primary_info_pages(site, homepage_html, fetch):
        words = normalized(visible_content(page_html))
        for href, label, prefix in anchor_rows(page_html):
            if safe_public_url(href) != href:
                continue
            parts = urlsplit(href)
            host = parts.hostname or ""
            if (host == urlsplit(site).hostname or host.endswith(
                    "." + urlsplit(site).hostname)
                    or classify(href) in ("SOCIAL", "TICKETING", "MEDIA")
                    or any(host == b or host.endswith("." + b)
                           for b in BLOCKED_FAMILIES)):
                continue
            chunks = [p for p in re.findall(
                r"[a-z0-9]+", host.removeprefix("www."))
                if len(p) >= 4 and p not in ("www", "com", "info", "site",
                                            "concert", "festival")]
            if not chunks:
                continue
            # A venue's hostname has to share a distinctive token with the
            # page's explicit location description; not just a footer icon.
            venue_named = any(re.search(
                r"\b(?:lieu|salle|scene|le lieu|the venue)\b.{0,160}\b"
                + re.escape(token) + r"\b", words) is not None
                for token in chunks)
            if not venue_named:
                continue
            root = "https://" + host + "/"
            if safe_root(root) is not None:
                candidates.add(root)
    return sorted(candidates)[:MAX_VENUE_ROOTS]


def venue_detail_matches(html, title, day_start, day_end, site):
    """A separate venue detail: named festival + matching date + direct link.

    One exact announced day within the first-party weekend is a legitimate
    independent corroboration; the primary site proves the complete range.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650000:
        return False
    try:
        visible = normalized(visible_content(html))
        base = normalized(re.sub(r"\s+20[2-4][0-9]$", "", title))
        if len(base) < 7 or not re.search(
                r"(?<![a-z0-9])" + re.escape(base) + r"(?![a-z0-9])",
                visible):
            return False
        year = day_start.year
        dates = {(a, b) for _x, _y, a, b in explicit_ranges(
            visible_content(html), year)}
        if not any(day_start <= a <= b <= day_end for a, b in dates):
            return False
        links = anchor_rows(html)
        back = []
        for href, label, _prefix in links:
            if safe_public_url(href) != href:
                continue
            parsed = urlsplit(href)
            if parsed.hostname != urlsplit(site).hostname:
                continue
            label = normalized(str(label))
            if any(x in label for x in ("infos", "programmation",
                                        "site officiel", "site du festival")):
                back.append(href)
        return bool(back)
    except (TypeError, ValueError, UnicodeError, KeyError):
        return False


def _venue_event_links(page_html, index_url, venue_root, title, year):
    base = normalized(re.sub(r"\s+20[2-4][0-9]$", "", title))
    unique = []
    for href, label, prefix in anchor_rows(page_html):
        words = normalized(label)
        if base not in words:
            continue
        target = safe_link(href, index_url, venue_root)
        if target is not None and target not in unique:
            unique.append(target)
    return unique[:MAX_EVENT_PAGES]


def verified_venue_reciprocity(site, title, dates, today,
                                fetch=fetch_public_html):
    """Return a unique independent venue host or fail closed."""
    if (safe_root(site) is None or not isinstance(title, str)
            or not re.fullmatch(r".{7,150} 20[2-4][0-9]", title)):
        return None
    try:
        first, last = map(date.fromisoformat, dates)
        current = date.fromisoformat(today)
        year = int(title.rsplit(" ", 1)[-1])
        if not current <= first <= last or first.year != year or last.year != year:
            return None
        homepage = fetch(site)
        primary_dates = verify_official_site_pages(
            site, homepage, title, year, today, fetch=fetch)
        if primary_dates != tuple(dates):
            return None
        venues = candidate_venue_roots(site, homepage, fetch=fetch)
        proven = []
        for venue in venues:
            try:
                index = fetch(venue)
                # A real venue's public index must lead to event content.
                agenda = [venue]
                for href, label, prefix in anchor_rows(index):
                    if "agenda" in normalized(label):
                        x = safe_link(href, venue, venue)
                        if x is not None and x not in agenda:
                            agenda.append(x)
                found = set()
                for index_url in agenda[:MAX_VENUE_INDEXES]:
                    page = index if index_url == venue else fetch(index_url)
                    for target in _venue_event_links(
                            page, index_url, venue, title, year):
                        if target in found or len(found) >= MAX_EVENT_PAGES:
                            continue
                        found.add(target)
                        detail = fetch(target)
                        if venue_detail_matches(
                                detail, title, first, last, site):
                            proven.append(venue)
                            break
                    if venue in proven:
                        break
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                continue
        unique = sorted(set(proven))
        return unique[0] if len(unique) == 1 else None
    except (TypeError, ValueError, UnicodeError, KeyError):
        return None


def private_proposal(title, site, dates, today, *, venue_root):
    if safe_root(site) is None or safe_root(venue_root) is None:
        return None
    if site == venue_root or slug_for(title) is None:
        return None
    try:
        first, last = map(date.fromisoformat, dates)
        now = date.fromisoformat(today)
        year = int(title.rsplit(" ", 1)[-1])
        if not now <= first <= last or first.year != year or last.year != year:
            return None
    except (TypeError, ValueError, OverflowError, KeyError):
        return None
    return {
        "slug": slug_for(title), "name": title,
        "startDate": first.isoformat(), "endDate": last.isoformat(),
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False, "lineup": [], "bands": 0,
        "price": None, "status": "Annoncé",
        "officialSite": site, "source": site,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": venue_root,
        "evidence": [venue_root, site], "verified_at": today,
    }


def validate_private_proposal(row, today):
    if (not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS
            or safe_root(row.get("originSlug")) is None
            or row.get("evidence") != [row.get("originSlug"),
                                       row.get("officialSite")]):
        return None
    try:
        observed = date.fromisoformat(row["verified_at"])
        checked = date.fromisoformat(today)
        if observed > checked or (checked - observed).days > 7:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")),
        row["verified_at"], venue_root=row["originSlug"])
    return row if expected == row else None


def validate_verified_row(proposal, verified, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {k: proposal[k] for k in ROW_KEYS}
    expected.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE)
    return expected if expected == verified else None


def independently_verify(proposal, today, fetch=fetch_public_html):
    """Cloud Publisher rebuilds both sites and their mutual event linkage."""
    if validate_private_proposal(proposal, today) is None:
        return None
    try:
        actual = verified_venue_reciprocity(
            proposal["officialSite"], proposal["name"],
            (proposal["startDate"], proposal["endDate"]), today, fetch)
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None
    if actual != proposal["originSlug"]:
        return None
    approved = {k: proposal[k] for k in ROW_KEYS}
    approved.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE)
    return approved
