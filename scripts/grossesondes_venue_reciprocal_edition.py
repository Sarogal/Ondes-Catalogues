"""The OFFICIAL festival website is the sole source for dates and place.

The independent venue site is ONLY evidence that a website belongs to the
named festival: its own dates/places are neither required nor reused. The
Publisher independently downloads the HTTPS festival website again and checks
its current-edition dates and editorial genre. It also recovers the reciprocal
official website link from a venue's historical or current event page. No
festival, venue, organizer or domain whitelist.

Never copy the external venue page's date into the festival catalogue.
This path stays append-only and does not invent geocoordinates or a lineup.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urljoin, urlsplit
import re

from dns_pinned_https import fetch_public_html, safe_public_url
from grossesondes_generic_directory_edition import (
    Heading, verify_official_site_pages,
)
from grossesondes_official_html_edition import (
    VisibleText, fold, explicit_ranges, dominant_visible_range,
    administrative_calendar_dates, CANCEL,
)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction
from festival_event_kind import touring_concert_stop
from grossesondes_institutional_edition import slug_for
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS
from source_qualification import Anchors, normalized, classify

PROOF_MODE = "generic-venue-reciprocal-edition.v1"
PRIVATE_NOTES = ("Provenance du site à revalider ; dates et lieu annoncés "
                 "par le seul site officiel. Artistes et GPS non déduits.")
PUBLISHED_NOTES = ("Domaine du festival corroboré par le lien réciproque "
                   "d'une salle ; dates contrôlées uniquement sur le site "
                   "officiel. Coordonnées et artistes à confirmer.")
PRIVATE_STATUS = "Domaine officiel à recouper, édition à relire"
PUBLISHED_STATUS = "Site officiel et édition revérifiés par le Publisher"
PRIVATE_CONFIDENCE = "Site officiel à attribuer, annonce primaire J/J+1"
PUBLISHED_CONFIDENCE = "Domaine attribué, dates du site officiel vérifiées"
BLOCKED_FAMILIES = frozenset(("google.com", "google.fr", "facebook.com",
                             "instagram.com", "twitter.com", "x.com",
                             "youtube.com", "linktr.ee", "weezevent.com",
                             "shotgun.live", "helloasso.com", "billetweb.fr"))
MAX_PRIMARY_PAGES = 3   # homepage and two primary same-host info links
MAX_VENUE_ROOTS = 4     # bounded candidate third-party domains
MAX_VENUE_INDEXES = 3   # root + two visible agenda links
MAX_EVENT_PAGES = 3     # at most 3 venue details; NO edition dates needed
STYLE_WITHOUT_BRAND = re.compile(
    r"\b(?:metal|rock|punk|metalcore|deathcore|grindcore|"
    r"stoner|doom|sludge|thrash)\b")

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


def venue_detail_matches(html, title, site):
    """Independent venue identity/backlink ONLY, NEVER date corroboration.

    A venue may describe the festival's PAST edition; it still establishes
    which domain belongs to it. Dates/location are exclusively retrieved
    from the CURRENT-EDITION official festival website, not from this page.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650000:
        return False
    try:
        base = normalized(re.sub(r"\s+20[2-4][0-9]$", "", title))
        headings = Heading()
        headings.feed(html)
        headings.close()
        if len(base) < 7:
            return False
        # An exact festival or programme heading, with or without year,
        # may establish identity. A footer or another concert cannot.
        named_heading = re.compile(
            r"^" + re.escape(base) +
            r"(?:\s+20[2-4][0-9])?(?:\s+(?:jour|day)\s+[1-7])?$")
        if sum(bool(named_heading.fullmatch(h)) for h in headings.headings) != 1:
            return False
        for href, label, _prefix in anchor_rows(html):
            if safe_public_url(href) != href:
                continue
            if urlsplit(href).hostname != urlsplit(site).hostname:
                continue
            role = normalized(str(label))
            if any(x in role for x in (
                    "infos", "programmation", "site officiel",
                    "site du festival")):
                return True
        return False
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



def first_party_hero_hint(html, title, today):
    """Research-only current festival date, when hero and brand are separate.

    This NEVER authorizes a festival. Only independent venue event + domain
    backlink (checked later by Publisher) may upgrade its evidence. Important
    for real first-party sites that use a slogan h1 and a dated event hero.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 650000
            or not isinstance(title, str)
            or not re.fullmatch(r".{7,150} 20[2-4][0-9]", title)):
        return None
    try:
        today_date = date.fromisoformat(today)
        year = int(title.rsplit(" ", 1)[-1])
        words = normalized(visible_content(html))
        brand = normalized(title.rsplit(" ", 1)[0])
        if (not brand or
                re.search(r"(?<![a-z0-9])" + re.escape(brand) +
                          r"(?![a-z0-9])", words) is None
                or CANCEL.search(words)):
            return None
        stripped = re.sub(
            r"(?<![a-z0-9])" + re.escape(brand) +
            r"(?:\s+20[2-4][0-9])?(?![a-z0-9])",
            " ", words)
        if STYLE_WITHOUT_BRAND.search(stripped) is None:
            return None
        ranges = {(first, end) for _a, _b, first, end
                  in explicit_ranges(visible_content(html), year)
                  if (first, end) not in administrative_calendar_dates(
                      html, title, year)}
        chosen = dominant_visible_range(ranges)
        if chosen is None:
            return None
        first, end = chosen
        if (not today_date <= first <= end
                or first.year != year or end.year != year
                or touring_concert_stop(html, first, end)
                or not no_same_edition_jsonld_contradiction(
                    html, title, first, end)):
            return None
        return first.isoformat(), end.isoformat()
    except (TypeError, ValueError, UnicodeError, OverflowError, KeyError):
        return None


def verified_venue_reciprocity(site, title, dates, today,
                                fetch=fetch_public_html):
    """Verify current festival dates ONLY at its site; venue attests domain."""
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
        if primary_dates is None:
            # Separate hero blocks are acceptable only if the venue later
            # confirms the festival's DOMAIN -- not the same edition dates.
            primary_dates = first_party_hero_hint(homepage, title, today)
        if primary_dates != tuple(dates):
            return None
        # A festival named "Rock Festival" is not evidence of rock MUSIC.
        # Require the genre to appear in the actual official description
        # independently of the brand and year. Electronic "hardcore" alone
        # deliberately does not qualify for a rock/metal/punk calendar.
        label = normalized(title.rsplit(" ", 1)[0])
        visible_words = normalized(visible_content(homepage))
        independent_genre = re.sub(
            r"(?<![a-z0-9])" + re.escape(label) +
            r"(?:\s+20[2-4][0-9])?(?![a-z0-9])",
            " ", visible_words)
        if STYLE_WITHOUT_BRAND.search(independent_genre) is None:
            return None
        venues = candidate_venue_roots(site, homepage, fetch=fetch)
        proven = []
        for venue in venues:
            try:
                index = fetch(venue)
                # A genuine venue's event may concern an OLDER edition;
                # it establishes ownership of the linked festival domain.
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
                        if venue_detail_matches(detail, title, site):
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
    """Publisher re-fetches primary dates; venue checks DOMAIN only."""
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
