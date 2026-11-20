"""Publisher proof for a NEW festival linked by an approved institutional event.

A website appearing in a PRIVATE dossier is never authority. Both the source
index and its SAME-HOST event detail must be re-fetched independently through
the reviewed institutional registry; that exact detail must visibly label an
external domain as the festival's website. Only then may the newly linked
HTTPS site be fetched through the public-IP-pinned network client. Both event
identity and complete visible dates must match. No inherited map/lineup data.
"""
from __future__ import annotations

from datetime import date
import re

from grossesondes_institutional_edition import (
    PRIVATE_KEYS, ROW_KEYS, trusted_source, slug_for,
    conflicts_with_signed_catalogue, independent_institutional_music_genre,
)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction
from grossesondes_institutional_edition import institutional_date
from grossesondes_official_html_edition import VisibleText, fold
from national_detail_qualification import _seen_again
from regional_festival_discovery import candidate_links
from source_qualification import Anchors, clean_url, classify, normalized
from festival_website_discovery import visible_event_website_links
from dns_pinned_https import safe_public_url, fetch_public_html
from official_watch import get_page

PROOF_MODE = "institutional-linked-organizer-edition.v1"
PRIVATE_NOTES = ("Site de festival associé par une fiche institutionnelle ; dates "
                 "à revérifier indépendamment. Artistes, lieu, coordonnées et prix non vérifiés.")
PRIVATE_STATUS = "Lien institutionnel et dates organisateur à revérifier"
PRIVATE_CONFIDENCE = "Agenda institutionnel + site lié (preuve privée)"
PUBLISHED_STATUS = "Lien institutionnel et dates organisateur revérifiés indépendamment"
PUBLISHED_CONFIDENCE = "Agenda institutionnel + site du festival (contrôle indépendant)"


def linked_site(detail_html, spec):
    """Require a single explicit, *visible* attributed festival website link.

    No links from JSON-LD without a date, scripts, hidden markup, general
    nav links or links to a foreign event are usable as authority.
    """
    if not isinstance(detail_html, str) or not 0 < len(detail_html) <= 650_000:
        return None
    try:
        parser = Anchors()
        parser.feed(detail_html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    title = re.sub(r"\s+20[2-4][0-9]$", "", spec["title"]).strip()
    role = lambda url: ("INSTITUTION" if url == spec["url"] else classify(url))
    choices = visible_event_website_links(
        parser.anchors, spec["url"], title, str(spec["year"]) + "-01-01",
        clean_url, role, normalized)
    sites = {x["candidate_url"] for x in choices
             if safe_public_url(x.get("candidate_url")) is not None}
    return next(iter(sites)) if len(sites) == 1 else None


def trusted_live_link(spec, today, institution_fetch=get_page):
    """Resolve untrusted link via today's approved INDEX -> exact detail."""
    approved = trusted_source(spec.get("index_url"), spec.get("index_page"),
                             spec.get("url"), spec.get("title"), today)
    if approved is None:
        return None
    try:
        index_html = institution_fetch(approved["index_page"])
        if not _seen_again(index_html, approved):
            return None
        candidates = candidate_links(index_html, approved["index_url"], today)
        theme_on_index = any(
            c.get("candidate_url") == approved["url"]
            and normalized(c.get("title")) == normalized(approved["title"])
            for c in candidates)
        # The same-host institutional DETAIL may supply a missing musical
        # genre, but the OpenData/PRIVATE label never counts as proof.
        detail_html = institution_fetch(approved["url"])
        if (not theme_on_index and not independent_institutional_music_genre(
                detail_html, approved["title"], approved["year"])):
            return None
        site = linked_site(detail_html, approved)
        if site is None:
            return None
        return site
    except (OSError, TypeError, ValueError, UnicodeError, KeyError):
        return None


def prove_dates(site_html, title, year, today):
    """Whole, exact-year visible dates and no contradictory same-edition JSON-LD.

    A concert tour with 'Fest' in the marketing name is not automatically
    a distinct festival edition. Require the absence of an explicit
    same-page touring-concert declaration close to the event announcement.
    """
    try:
        visible = VisibleText()
        visible.feed(site_html)
        visible.close()
        text = " ".join(fold(" ".join(visible.parts)).split())
        # A strong touring statement vetoes an otherwise ambiguous Fest name.
        if re.search(r"\b(?:tournee itinerante|tournee de [0-9]+ concerts?|"
                     r"concerts? de la tournee|date de la tournee|"
                     r"concert tour|tour de concerts?)\b", text):
            return None
        start, end = institutional_date(site_html, title, year)
        if (start < date.fromisoformat(today) or
                start.year != year or end.year != year or
                not no_same_edition_jsonld_contradiction(site_html, title, start, end)):
            return None
        return start.isoformat(), end.isoformat()
    except (OSError, TypeError, ValueError, UnicodeError):
        return None


def private_proposal(spec, site, dates, today):
    """Build the only allowed, map-free representation of a new edition."""
    trusted = trusted_source(spec.get("index_url"), spec.get("index_page"),
                             spec.get("url"), spec.get("title"), today)
    if trusted is None or safe_public_url(site) is None:
        return None
    try:
        start, end = (date.fromisoformat(x) for x in dates)
        checked = date.fromisoformat(today)
    except (ValueError, TypeError):
        return None
    if (not checked <= start <= end or start.year != trusted["year"]
            or end.year != trusted["year"] or (end - start).days > 7):
        return None
    return {
        "slug": slug_for(trusted["title"]), "name": trusted["title"],
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False, "lineup": [], "bands": 0, "price": None,
        "status": "Annoncé", "officialSite": site, "source": trusted["url"],
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS, "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": trusted["index_url"],
        "evidence": [trusted["index_url"], trusted["index_page"], trusted["url"], site],
        "verified_at": today,
    }


def validate_private_proposal(proposal, today):
    """All fields must equal a freshly reconstructed, sanitized proposal."""
    if not isinstance(proposal, dict) or set(proposal) != ROW_KEYS | PRIVATE_KEYS:
        return None
    evidence = proposal.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 4:
        return None
    origin, page, detail, site = evidence
    spec = trusted_source(origin, page, detail, proposal.get("name"), today)
    if (spec is None or proposal.get("originSlug") != origin
            or proposal.get("officialSite") != site):
        return None
    checked = proposal.get("lastVerified")
    try:
        if (not isinstance(checked, str)
                or date.fromisoformat(checked) > date.fromisoformat(today)):
            return None
    except (ValueError, TypeError):
        return None
    expected = private_proposal(
        spec, site, (proposal.get("startDate"), proposal.get("endDate")), checked)
    return spec if expected == proposal else None


def validate_verified_row(proposal, verified, today):
    """The stage accepts only the exact map-free, independent row contract."""
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        verificationStatus=PUBLISHED_STATUS, sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=("Fiche institutionnelle relue et lien vers le site du festival "
               "revérifié ; dates exactes confirmées sur le site lié. "
               "Artistes, lieu, coordonnées et tarifs à confirmer."),
    )
    return expected if verified == expected else None


def independently_verify(proposal, today, institution_fetch=get_page,
                         organizer_fetch=fetch_public_html):
    """Publisher redoes trusted index, exact link and fresh organizer HTTPS."""
    spec = validate_private_proposal(proposal, today)
    if spec is None:
        return None
    site = trusted_live_link(spec, today, institution_fetch)
    if site is None or site != proposal["officialSite"]:
        return None
    try:
        html = organizer_fetch(site)
    except (OSError, TypeError, UnicodeError, ValueError, KeyError):
        return None
    dates = prove_dates(html, proposal["name"], spec["year"], today)
    if dates != (proposal["startDate"], proposal["endDate"]):
        return None
    verified = {key: proposal[key] for key in ROW_KEYS}
    verified.update(
        verificationStatus=PUBLISHED_STATUS, sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=("Fiche institutionnelle relue et lien vers le site du festival "
               "revérifié ; dates exactes confirmées sur le site lié. "
               "Artistes, lieu, coordonnées et tarifs à confirmer."),
    )
    return verified
