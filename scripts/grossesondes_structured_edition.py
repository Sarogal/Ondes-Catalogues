"""Independent publication proof for a next-year festival edition.

The private new-edition record is NEVER proof. Only the immutable published
parent's registered officialSite may be downloaded by the public synchronizer.
A new edition can be added to the list but gets no map pin, venue, inherited
bands, price or sessions. The JSON-LD must specify the precise year AND dates.
"""
from datetime import date
import re

from grossesondes_structured_roster import (
    JsonLD, walk, iso_day, edition_name, ALLOWED_EVENT_TYPES,
    SENSITIVE_STATUSES,
)

PROOF_MODE = "structured-edition.v1"
SLUG = re.compile(r"^(.+)-(20[2-4][0-9])$")
PRIVATE_NOTES = (
    "Édition annoncée dans les données structurées du site officiel ; "
    "dates de l'événement vérifiables. Lieu, séances, tarifs et "
    "coordonnées restent à confirmer."
)
PRIVATE_STATUS = "Édition et dates à confirmer indépendamment avant publication"
PRIVATE_CONFIDENCE = "Site officiel (JSON-LD privé, preuve publique requise)"
PUBLISHED_STATUS = "Édition et dates vérifiées indépendamment ; lieu et séances à confirmer"
PUBLISHED_CONFIDENCE = "Site officiel (JSON-LD vérifié indépendamment)"
ROW_KEYS = {
    "slug", "name", "startDate", "endDate", "city", "department",
    "region", "venue", "lat", "lon", "showOnMap",
    "dateRangeIsContinuous", "lineup", "bands", "price", "status",
    "officialSite", "source", "lastVerified", "notes",
    "verificationStatus", "sourceConfidence",
}
PRIVATE_KEYS = {"proofMode", "originSlug", "evidence", "verified_at"}


def validate_structured_edition(proposal, parent, html, today):
    """Return sanitized new row or None; never partially accept."""
    if not (isinstance(proposal, dict) and isinstance(parent, dict)
            and isinstance(html, str) and 0 < len(html) <= 1_400_000):
        return None
    if set(proposal) != ROW_KEYS | PRIVATE_KEYS:
        return None
    if proposal.get("proofMode") != PROOF_MODE:
        return None
    old_slug, new_slug = parent.get("slug"), proposal.get("slug")
    old_match = SLUG.fullmatch(old_slug) if isinstance(old_slug, str) else None
    new_match = SLUG.fullmatch(new_slug) if isinstance(new_slug, str) else None
    if not old_match or not new_match:
        return None
    old_year, year = int(old_match.group(2)), int(new_match.group(2))
    if not (year == old_year + 1 and year in (2027, 2028)
            and old_match.group(1) == new_match.group(1)
            and proposal["originSlug"] == old_slug):
        return None
    title = proposal["name"]
    url = parent.get("officialSite")
    if not (isinstance(title, str) and 8 <= len(title) <= 180
            and isinstance(parent.get("name"), str)
            and len(edition_name(title)) >= 8
            and edition_name(title) == edition_name(parent["name"])
            and re.search(r"\b" + str(year) + r"\b", title)
            and isinstance(url, str) and url.startswith("https://")
            and proposal["officialSite"] == proposal["source"] == url
            and proposal["evidence"] == [url]):
        return None
    start = iso_day(proposal["startDate"])
    end = iso_day(proposal["endDate"])
    checked = iso_day(proposal["lastVerified"])
    received = iso_day(today)
    if not (start and end and checked and received
            and proposal["startDate"] == start.isoformat()
            and proposal["endDate"] == end.isoformat()
            and proposal["lastVerified"] == checked.isoformat()
            and proposal["verified_at"] == proposal["lastVerified"]
            and checked <= received <= start
            and start.year == end.year == year
            and 0 <= (end - start).days <= 7):
        return None
    if not (proposal["status"] == "Annoncé"
            and proposal["showOnMap"] is False
            and proposal["dateRangeIsContinuous"] is False
            and proposal["lineup"] == []
            and type(proposal["bands"]) is int and proposal["bands"] == 0
            and all(proposal[k] is None for k in (
                "city", "department", "region", "venue", "lat", "lon", "price"))
            and proposal["notes"] == PRIVATE_NOTES
            and proposal["verificationStatus"] == PRIVATE_STATUS
            and proposal["sourceConfidence"] == PRIVATE_CONFIDENCE):
        return None
    parser = JsonLD()
    parser.feed(html)
    seen_matching = False
    for document in parser.documents[:30]:
        for event in walk(document):
            types = event.get("@type")
            if not isinstance(types, list):
                types = [types]
            types = {str(t).rsplit("/", 1)[-1].casefold() for t in types}
            if not types.intersection(ALLOWED_EVENT_TYPES):
                continue
            event_name = event.get("name")
            if (not isinstance(event_name, str)
                    or edition_name(event_name) != edition_name(title)
                    or str(year) not in re.findall(r"\b20[2-4][0-9]\b", event_name)):
                continue
            # Any conflicting same-edition event invalidates the whole page.
            ev_start = iso_day(event.get("startDate"))
            ev_end = iso_day(event.get("endDate"))
            status = str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
            if (event_name.strip() != title.strip()
                    or ev_start != start or ev_end != end
                    or status in SENSITIVE_STATUSES):
                return None
            seen_matching = True
    if not seen_matching:
        return None
    result = {k: proposal[k] for k in ROW_KEYS}
    result["verificationStatus"] = PUBLISHED_STATUS
    result["sourceConfidence"] = PUBLISHED_CONFIDENCE
    return result


def conflicts_with_existing(proposal, calendar, history):
    """Block duplicate identities even when slugs differ or archives hold it."""
    slug = proposal.get("slug")
    title = proposal.get("name")
    start = proposal.get("startDate")
    if not (isinstance(slug, str) and isinstance(title, str)
            and isinstance(start, str)):
        return True
    year = start[:4]
    for row in list(calendar) + list(history):
        if row.get("slug") == slug:
            return True
        row_name = row.get("name", "")
        row_year = str(row.get("startDate") or "")[:4]
        if (isinstance(row_name, str)
                and edition_name(row_name) == edition_name(title)
                and (row_year == year or
                     year in re.findall(r"\b20[2-4][0-9]\b", row_name))):
            return True
    return False
