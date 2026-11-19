"""Strict generic institutionally listed festival proof; no named-event adapters.

The private patch is only a selector. The publisher first downloads an
institutional INDEX from the immutable, code-reviewed registry, checks that a
specific edition title still links to a same-origin detail page, and only THEN
fetches the detail. Private sources never authorize network destinations.
"""
from __future__ import annotations

from datetime import date
import re
import sys
import unicodedata
from pathlib import Path

ENGINE = str(Path(__file__).resolve().parents[1] / "festival-automation")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from grossesondes_archived_html_intake import official_date
from grossesondes_structured_edition import (
    ROW_KEYS, PRIVATE_KEYS, no_same_edition_jsonld_contradiction, conflicts_with_existing,
)
from national_detail_qualification import _seen_again
from national_discovery_queue import _safe_origin_link
from official_watch import get_page, permitted_url
from regional_agenda_pagination import canonical_page_url
from regional_festival_discovery import APPROVED, candidate_links
from source_qualification import normalized

PROOF_MODE = "institutional-visible-edition.v1"
PRIVATE_NOTES = ("Dates mentionnées sur un agenda institutionnel ; lieu, "
                 "artistes, tarif et coordonnées non vérifiés.")
PRIVATE_STATUS = "Dates institutionnelles à revérifier indépendamment avant publication"
PRIVATE_CONFIDENCE = "Agenda institutionnel (observation privée)"
PUBLISHED_STATUS = "Dates revérifiées sur agenda institutionnel ; lieu et coordonnées non confirmés"
PUBLISHED_CONFIDENCE = "Agenda institutionnel (fiche et index relus indépendamment)"


def slug_for(title):
    if not isinstance(title, str) or len(title) > 180:
        return None
    folded = unicodedata.normalize("NFKD", title.casefold())
    base = "".join(x for x in folded if not unicodedata.combining(x))
    slug = "-".join(re.findall(r"[a-z0-9]+", base))
    return slug if 8 <= len(slug) <= 160 and re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*-20[2-4][0-9]", slug) else None


def trusted_source(origin, index_page, detail, title, today):
    """Use only a reviewed index root and a canonical page of that index."""
    if (not isinstance(origin, str) or origin not in APPROVED
            or not isinstance(index_page, str) or not isinstance(detail, str)
            or not _safe_origin_link(detail, origin)
            or not permitted_url(detail)
            or not isinstance(title, str) or slug_for(title) is None):
        return None
    if (index_page != origin
            and canonical_page_url(index_page, origin, permitted_url)
                != index_page):
        return None
    year = int(slug_for(title).rsplit("-", 1)[-1])
    if year not in (2027, 2028):
        return None
    try:
        if date.fromisoformat(today).year > year:
            return None
    except (TypeError, ValueError):
        return None
    return {
        "index_url": origin, "index_page": index_page, "url": detail,
        "title": title, "year": year,
    }


def private_proposal(source, dates, today):
    """Sanitize a two-day private observation; no data from old editions."""
    if not isinstance(source, dict) or not isinstance(dates, tuple):
        return None
    origin, page, detail = (source.get("index_url"),
                            source.get("index_page"), source.get("url"))
    title = source.get("title")
    spec = trusted_source(origin, page, detail, title, today)
    if spec is None or len(dates) != 2:
        return None
    try:
        first, last = (date.fromisoformat(x) for x in dates)
        current = date.fromisoformat(today)
    except (ValueError, TypeError):
        return None
    if (not current <= first <= last
            or first.year != last.year != spec["year"]
            or (last - first).days > 7):
        return None
    proposal = {
        "slug": slug_for(title), "name": title,
        "startDate": first.isoformat(), "endDate": last.isoformat(),
        "city": None, "department": None, "region": None,
        "venue": None, "lat": None, "lon": None,
        "showOnMap": False, "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Annoncé", "officialSite": detail, "source": detail,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": origin,
        "evidence": [origin, page, detail], "verified_at": today,
    }
    return proposal


def validate_private_proposal(proposal, today):
    if not isinstance(proposal, dict) or set(proposal) != ROW_KEYS | PRIVATE_KEYS:
        return None
    evidence = proposal.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 3:
        return None
    origin, page, detail = evidence
    spec = trusted_source(origin, page, detail, proposal.get("name"), today)
    if (spec is None or proposal.get("proofMode") != PROOF_MODE
            or proposal.get("originSlug") != origin
            or proposal.get("officialSite") != detail
            or proposal.get("source") != detail
            or proposal.get("slug") != slug_for(proposal.get("name"))
            or proposal.get("status") != "Annoncé"
            or proposal.get("lastVerified") != proposal.get("verified_at")
            or proposal.get("notes") != PRIVATE_NOTES
            or proposal.get("verificationStatus") != PRIVATE_STATUS
            or proposal.get("sourceConfidence") != PRIVATE_CONFIDENCE
            or proposal.get("showOnMap") is not False
            or proposal.get("dateRangeIsContinuous") is not False
            or proposal.get("lineup") != []
            or type(proposal.get("bands")) is not int
            or proposal.get("bands") != 0
            or any(proposal.get(k) is not None for k in
                   ("city","department","region","venue","lat","lon","price"))):
        return None
    try:
        first = date.fromisoformat(proposal["startDate"])
        last = date.fromisoformat(proposal["endDate"])
        checked = date.fromisoformat(proposal["lastVerified"])
        current = date.fromisoformat(today)
    except (ValueError, TypeError, KeyError):
        return None
    if (not checked <= current <= first <= last
            or first.year != spec["year"] or last.year != spec["year"]
            or (last-first).days > 7
            or first.isoformat() != proposal["startDate"]
            or last.isoformat() != proposal["endDate"]):
        return None
    return spec


def independently_fetch(proposal, today, fetch=get_page):
    """Return HTML only if a fresh, approved live index proves the exact link.

    A proposed URL is NEVER fetched until the live index establishes it as an
    actual event link with the same title AND festival musical theme.
    """
    spec = validate_private_proposal(proposal, today)
    if spec is None:
        return None
    try:
        index_html = fetch(spec["index_page"])
        if not _seen_again(index_html, spec):
            return None
        # A generic "festival" navigation link is not proof of a metal,
        # hard-rock or related musical event. Re-run the original genre-aware
        # institutional discovery filter on the independently fetched index.
        matches = candidate_links(index_html, spec["index_url"], today)
        if not any(x.get("candidate_url") == spec["url"]
                   and normalized(x.get("title")) == normalized(spec["title"])
                   for x in matches):
            return None
        return fetch(spec["url"])
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def validate_independent(proposal, html, today):
    """Build ONLY the verified minimal row; never inherit geolocation/lineup."""
    spec = validate_private_proposal(proposal, today)
    if spec is None or not isinstance(html, str):
        return None
    name = re.fullmatch(r"(.{8,150}?)\s+(20[2-4][0-9])",
                        proposal["name"].strip())
    if name is None or int(name.group(2)) != spec["year"]:
        return None
    try:
        dates = official_date(html, {"name": name.group(1)}, spec["year"])
    except (ValueError, TypeError, UnicodeError):
        return None
    if dates is None or tuple(x.isoformat() for x in dates) != (
            proposal["startDate"], proposal["endDate"]):
        return None
    if not no_same_edition_jsonld_contradiction(
            html, proposal["name"], *dates):
        return None
    approved = {key: proposal[key] for key in ROW_KEYS}
    approved["verificationStatus"] = PUBLISHED_STATUS
    approved["sourceConfidence"] = PUBLISHED_CONFIDENCE
    approved["notes"] = ("Dates revérifiées sur une fiche institutionnelle, "
                         "retrouvée dans son agenda officiel. "
                         "Lieu, artistes, coordonnées et tarifs à confirmer.")
    return approved


def conflicts_with_signed_catalogue(proposal, published, history):
    if conflicts_with_existing(proposal, published, history):
        return True
    # A different title/slug for the same edition MUST not use an already
    # published source URL as proof of a second festival.
    year = proposal["startDate"][:4]
    return any(isinstance(row, dict)
               and row.get("officialSite") == proposal["officialSite"]
               and str(row.get("startDate") or "")[:4] == year
               for row in list(published) + list(history))
