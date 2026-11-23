"""Autonomous NEW festival edition, explicitly announced without precise dates.

The trusted authority is the CURRENT first-party festival website, not an
archive or a second publisher. A private research lead only nominates a
canonical HTTPS host. The Publisher independently fetches that same host,
checks festival ownership/genre and confirms an unambiguous future edition.

No invented dates, performers, location, coordinates or venue. This route
never treats a fundraising proposal, an old year or a touring concert as a
confirmed festival edition.
"""
from __future__ import annotations

from datetime import date
import re

from dns_pinned_https import fetch_public_html
from grossesondes_first_party_direct_edition import (
    branded_official_site, safe_root, MAX_OFFICIAL_HTML,
)
from grossesondes_institutional_edition import slug_for
from grossesondes_official_html_edition import (
    VisibleText, fold, explicit_ranges,
)
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS

PROOF_MODE = "generic-first-party-direct-undated.v1"
PRIVATE_NOTES = (
    "Édition future annoncée par le festival ; dates à confirmer. "
    "Lieu précis, artistes et coordonnées non établis."
)
PRIVATE_STATUS = "Édition sans dates à revérifier sur le site officiel"
PRIVATE_CONFIDENCE = "Site officiel propre au festival (observation privée)"
PUBLISHED_STATUS = "Édition future confirmée sur le site officiel ; dates à confirmer"
PUBLISHED_CONFIDENCE = "Site officiel (annonce future revérifiée sans dates)"
PUBLISHED_NOTES = (
    "Édition future annoncée et revérifiée directement sur le site officiel. "
    "Dates à confirmer ; lieu précis, artistes et coordonnées non établis."
)

# Positive future-edition phrases, not loose year hints or future speculation.
# These are structural phrases valid for ANY festival, never a named roster.
FUTURE = (
    r"\b(?:edition(?:\s+[0-9]{1,2})?\s*"
    r"(?:[-–—·•:]\s*)?"
    r"(?:(?:en|ete|printemps|automne|hiver)\s+)?YEAR_HERE"
    r"|prochaine\s+edition\s+(?:en\s+)?YEAR_HERE"
    r"|rendez\s+vous\s+en\s+YEAR_HERE"
    r"|de\s+retour\s+en\s+YEAR_HERE)\b"
)
UNCERTAIN = re.compile(
    r"\b(?:si|possible|potentiel|eventuel|hypothetique|"
    r"projet|preparation|preparer|envisage|sous reserve|"
    r"financement|collecte de fonds|annule|annulation|"
    r"cancelled|reporte)\b"
)
YEAR = re.compile(r"(?<!\d)20[2-4]\d(?!\d)")


def confirmed_future_without_dates(site, title, html, today):
    """Verify one future-edition assertion visible on a branded official root."""
    if (safe_root(site) != site
            or not isinstance(title, str)
            or slug_for(title) is None
            or not isinstance(html, str)
            or not 0 < len(html) <= MAX_OFFICIAL_HTML):
        return False
    try:
        year = int(title.rsplit(" ", 1)[-1])
        now = date.fromisoformat(today)
        if not now.year <= year <= now.year + 2:
            return False
        if not branded_official_site(site, title, html):
            return False
        parser = VisibleText()
        parser.feed(html)
        parser.close()
        visible = " ".join(fold(" ".join(parser.parts)).split())
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False
    if not visible:
        return False
    # An actual dated edition must use the ordinary dated Publisher, not
    # a misleading "dates to confirm" fallback.
    if explicit_ranges(visible, year):
        return False
    candidates = list(re.finditer(
        FUTURE.replace("YEAR_HERE", str(year)), visible))
    for match in candidates:
        # Current home hero or prominently visible announcement, not
        # a footer/related-event archive miles away in the document.
        if match.start() > 2400:
            continue
        window = visible[max(0, match.start()-80):match.end()+120]
        if UNCERTAIN.search(window):
            continue
        # Conflicting year-specific dates should not be erased, and a
        # different-year announcement must not stand in for this edition.
        if YEAR.search(match.group()) and str(year) in match.group():
            return True
    return False


def private_proposal(title, site, today):
    """Minimal untrusted research claim: no coordinates/dates or inherited art."""
    if (not isinstance(title, str)
            or slug_for(title) is None
            or safe_root(site) != site):
        return None
    try:
        year = int(title.rsplit(" ", 1)[-1])
        current = date.fromisoformat(today)
    except (TypeError, ValueError, OverflowError):
        return None
    if not current.year <= year <= current.year + 2:
        return None
    return {
        "slug": slug_for(title), "name": title,
        "startDate": None, "endDate": None,
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Dates à venir",
        "officialSite": site, "source": site,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE,
        "originSlug": site, "evidence": [site], "verified_at": today,
    }


def validate_private_proposal(row, today):
    """Private records are selectors, never themselves proof of an event."""
    if (not isinstance(row, dict)
            or set(row) != ROW_KEYS | PRIVATE_KEYS
            or row.get("proofMode") != PROOF_MODE
            or row.get("originSlug") != row.get("officialSite")
            or row.get("evidence") != [row.get("officialSite")]):
        return None
    try:
        observed = date.fromisoformat(row["verified_at"])
        now = date.fromisoformat(today)
        if observed > now or (now - observed).days > 7:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"), row["verified_at"])
    return row if expected == row else None


def independently_verify(proposal, today, fetch=fetch_public_html):
    """Re-download only the independently bounded first-party festival root."""
    if validate_private_proposal(proposal, today) is None:
        return None
    site = proposal["officialSite"]
    try:
        html = fetch(site)
        if not confirmed_future_without_dates(
                site, proposal["name"], html, today):
            return None
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        return None
    row = {key: proposal[key] for key in ROW_KEYS}
    row.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
    )
    return row


def validate_verified_row(proposal, verified, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        notes=PUBLISHED_NOTES,
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
    )
    return expected if expected == verified else None
