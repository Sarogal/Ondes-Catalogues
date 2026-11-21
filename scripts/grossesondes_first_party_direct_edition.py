"""Autonomous first-party festival admission: official dates require no second site.

A discovered HTTPS DOMAIN is an untrusted nomination. Only a distinctive
festival-owned name/domain, visible first-party editorial identity, upcoming
dates, genre evidence independent of the name, and an independent Publisher
refetch can establish a minimal publication. No named festival, organizer,
source-domain, town or venue allowlist; no external repetition of dates.
A conflicting cancellation, tour, JSON-LD event, ambiguous festival identity,
or a hosted ticket/media platform fails closed. No location or coordinates
are guessed from a historical festival or private discovery hint.
"""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlsplit

from dns_pinned_https import safe_public_url, fetch_public_html
from grossesondes_generic_directory_edition import (
    verify_official_site_pages,
)
from grossesondes_venue_reciprocal_edition import (
    safe_root, visible_content, first_party_hero_hint,
    STYLE_WITHOUT_BRAND, BLOCKED_FAMILIES,
)
from grossesondes_official_html_edition import VisibleParagraphs, explicit_ranges
from grossesondes_institutional_edition import slug_for
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS
from source_qualification import normalized, classify

PROOF_MODE = "generic-first-party-direct-edition.v1"
PRIVATE_NOTES = ("Édition annoncée sur le domaine du festival, dates à relire "
                 "par le Publisher ; adresse exacte, artistes et GPS inconnus.")
PUBLISHED_NOTES = ("Édition et dates revérifiées directement sur le site "
                   "officiel du festival. Aucun recoupement extérieur des dates "
                   "n'est requis. Adresse exacte et GPS à compléter.")
PRIVATE_STATUS = "Source officielle à relire indépendamment"
PUBLISHED_STATUS = "Site et édition officielle revérifiés"
PRIVATE_CONFIDENCE = "Domaine propre au festival + annonce primaire (J/J+1)"
PUBLISHED_CONFIDENCE = "Domaine du festival + annonce officielle revérifiée"
# Generic web/genre words are not distinguishing festival ownership.
GENERIC_WORDS = frozenset((
    "festival", "festivals", "metal", "hard", "rock", "music",
    "musique", "edition", "open", "plein", "air", "live",
))
MAX_OFFICIAL_HTML = 650_000
# Only an explicitly printed town beside the current festival date can be
# copied. It is NOT a geocoder or a second-source date confirmation.
CITY_AFTER_DATE = re.compile(
    r"(?:\b(?:à|au|in|at)\s+|[·•]\s*)"
    r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,55}"
    r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,40}){0,2})")
CITY_FORBIDDEN = frozenset(("Festival", "France", "Programmation",
                             "Billetterie", "Musique", "Concert",
                             "Rock", "Metal", "Punk"))



def branded_official_site(site, title, html):
    """Distinctive branded domain AND visible first-party festival identity.

    This is stronger than a third-party URL hint, but does not require an
    external site to repeat any edition claim. A festival using a generic
    organizer site can instead use a more specific linked provenance route.
    """
    if (safe_root(site) is None or not isinstance(title, str)
            or not re.fullmatch(r".{7,150} 20[2-4][0-9]", title)
            or not isinstance(html, str)
            or not 0 < len(html) <= MAX_OFFICIAL_HTML):
        return False
    host = urlsplit(site).hostname or ""
    if (classify(site) in ("TICKETING", "SOCIAL", "MEDIA", "THIRD_PARTY")
            or any(host == bad or host.endswith("." + bad)
                   for bad in BLOCKED_FAMILIES)):
        return False
    # One distinctive token must tie the title to this domain. Festival
    # domain naming is open-world; no trusted organizer registry is used.
    core_name = title.rsplit(" ", 1)[0]
    host_key = "".join(re.findall(r"[a-z0-9]+", normalized(
        host.removeprefix("www.").split(".")[0])))
    words = re.findall(r"[a-z0-9]+", normalized(core_name))
    distinctive = [
        w for w in words if len(w) >= 5 and w not in GENERIC_WORDS
    ]
    if not distinctive or not any(w in host_key for w in distinctive):
        # Preserve unbroken brand tokens such as "Festibarock'in".
        brand_key = "".join(words)
        if len(brand_key) < 9 or brand_key not in host_key:
            return False
    visible = normalized(visible_content(html))
    name = normalized(core_name)
    if (len(name) < 7 or
            re.search(r"(?<![a-z0-9])" + re.escape(name) +
                      r"(?![a-z0-9])", visible) is None or
            "festival" not in visible):
        return False
    # Never classify the genre from the brand: a festival named "Rock Fest"
    # could actually advertise only electronic music or cooking.
    outside_brand = re.sub(
        r"(?<![a-z0-9])" + re.escape(name) +
        r"(?:\s+20[2-4][0-9])?(?![a-z0-9])", " ", visible)
    return STYLE_WITHOUT_BRAND.search(outside_brand) is not None



def official_city_on_current_date(html, title, dates):
    """Read the current edition's city ONLY if printed next to its dates.

    Never inherit locations from older festival editions. Ambiguous cities
    or unlabelled venue names remain absent and can be revisited via future
    geo enrichment; no external event announcement is required.
    """
    if not isinstance(html, str) or not 0 < len(html) <= MAX_OFFICIAL_HTML:
        return None
    try:
        start, end = map(date.fromisoformat, dates)
        parser = VisibleParagraphs()
        parser.feed(html)
        parser.close()
        locations = set()
        for block in " ".join(parser.parts).split(VisibleParagraphs.SEP):
            if not 0 < len(block) <= 900:
                continue
            printed = [
                (offset, finish)
                for offset, finish, a, b
                in explicit_ranges(block, start.year)
                if (a, b) == (start, end)
            ]
            if not printed:
                continue
            # Only use town names immediately AFTER current official dates,
            # not a previous edition, contact footer, or an unrelated venue.
            for _offset, finish in printed:
                for matched in CITY_AFTER_DATE.finditer(
                        block, finish, min(len(block), finish + 85)):
                    city = matched.group(1).strip()
                    if (len(city) >= 3
                            and city not in CITY_FORBIDDEN
                            and re.search(r"[0-9<>]", city) is None):
                        locations.add(city)
        return next(iter(locations)) if len(locations) == 1 else None
    except (ValueError, TypeError, UnicodeError, KeyError):
        return None


def verify_first_party_claims(site, title, today, fetch=fetch_public_html):
    """Read official current-edition dates and optional city in ONE download."""
    if safe_root(site) is None:
        return None
    try:
        html = fetch(site)
        if not branded_official_site(site, title, html):
            return None
        year = int(title.rsplit(" ", 1)[-1])
        dates = verify_official_site_pages(
            site, html, title, year, today, fetch=fetch)
        if dates is None:
            dates = first_party_hero_hint(html, title, today)
        if dates is None:
            return None
        start, end = (date.fromisoformat(x) for x in dates)
        if (start < date.fromisoformat(today) or start.year != year
                or end.year != year or start > end
                or (end - start).days > 7):
            return None
        return tuple(dates), official_city_on_current_date(html, title, dates)
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None



def verify_first_party_edition(site, title, today, fetch=fetch_public_html):
    """Compatibility wrapper: official dates only, no second event source."""
    claims = verify_first_party_claims(site, title, today, fetch)
    return claims[0] if claims is not None else None


def private_proposal(title, site, dates, today, *, city=None):
    if (safe_root(site) is None or slug_for(title) is None
            or not re.fullmatch(r".{7,150} 20[2-4][0-9]", title)):
        return None
    try:
        first, last = map(date.fromisoformat, dates)
        year = int(title.rsplit(" ", 1)[-1])
        now = date.fromisoformat(today)
        if (first < now or first.year != year or last.year != year
                or first > last or (last - first).days > 7):
            return None
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    if (city is not None
            and (not isinstance(city, str)
                 or not 3 <= len(city) <= 110
                 or re.search(r"[<>\x00-\x1f0-9]", city))):
        return None
    return {
        "slug": slug_for(title), "name": title,
        "startDate": first.isoformat(), "endDate": last.isoformat(),
        "city": city, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False, "lineup": [], "bands": 0,
        "price": None, "status": "Annoncé",
        "officialSite": site, "source": site,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": site,
        "evidence": [site], "verified_at": today,
    }


def validate_private_proposal(row, today):
    if (not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS
            or row.get("originSlug") != row.get("officialSite")
            or row.get("evidence") != [row.get("officialSite")]):
        return None
    try:
        observed = date.fromisoformat(row["verified_at"])
        now = date.fromisoformat(today)
        if observed > now or (now - observed).days > 7:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")), row.get("verified_at"),
        city=row.get("city"))
    return row if expected == row else None


def independently_verify(proposal, today, fetch=fetch_public_html):
    """Do not accept private proof text: re-download primary site live."""
    if validate_private_proposal(proposal, today) is None:
        return None
    claims = verify_first_party_claims(
        proposal["officialSite"], proposal["name"], today, fetch)
    if (claims is None
            or claims[0] != (proposal["startDate"], proposal["endDate"])
            or (proposal["city"] is not None
                and proposal["city"] != claims[1])):
        return None
    row = {key: proposal[key] for key in ROW_KEYS}
    row.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE)
    return row


def validate_verified_row(proposal, verified, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE)
    return expected if expected == verified else None
