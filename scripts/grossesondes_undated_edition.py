"""Generic, no-date future-edition proof from a SIGNED historical organizer.

A signed historical festival establishes only identity and a first-party HTTPS
origin, NEVER a future date, address, artist, tariff, or map pin. The current
organizer must explicitly announce the future EDITION. Observations can be
proposed privately after two days; the Publisher independently refetches the
original signed organizer URL and applies this exact contract.

No named festival/artist/organizer/city/site allowlist is used here.
"""
from datetime import date
import re

from grossesondes_official_html_edition import VisibleText, fold, explicit_ranges, CANCEL
from grossesondes_structured_edition import (
    ROW_KEYS, PRIVATE_KEYS, pinned_parent_identity, edition_name,
)
from grossesondes_structured_roster import iso_day

PROOF_MODE = "official-archived-undated-edition.v1"
PRIVATE_NOTES = (
    "Retour de l'édition future explicitement annoncé sur le site officiel ; "
    "dates exactes, artistes, lieu futur et coordonnées non établis. "
    "Ne pas déduire les informations de l'édition précédente."
)
PRIVATE_STATUS = "Édition future annoncée ; dates à confirmer par l'organisateur"
PRIVATE_CONFIDENCE = "Site officiel historique (annonce 2027 en vérification privée)"
PUBLISHED_STATUS = "Édition future revérifiée sur le site officiel ; dates à confirmer"
PUBLISHED_CONFIDENCE = "Site officiel (édition future confirmée, sans dates)"

# Only positive, YEAR-SPECIFIC organizer assertions are admissible. "Préparer
# 2027", "possible 2027", footer copyright, or last year's lineup are NOT
# unequivocal confirmation. These are structural phrasing patterns, never
# festival identities or preferred sources.
FUTURE_ANNOUNCEMENT = re.compile(
    r"(?:\brendez[\W_]+vous[\W_]+en[\W_]+{year}\b"
    r"|\bde[\W_]+retour[\W_]+en[\W_]+{year}\b"
    r"|\brevient[\W_]+en[\W_]+{year}\b"
    r"|\bedition[\W_]+(?:[0-9]{{1,2}}[\W_]+)?"
    r"(?:ete[\W_]+|hiver[\W_]+|printemps[\W_]+)?{year}\b"
    r"|\bprochaine[\W_]+edition[\W_]+(?:en[\W_]+)?{year}\b)"
)


def visible_future_edition_without_dates(html, parent, year):
    """Strong positive announcement, with no competing visible precise dates."""
    if (not isinstance(html, str) or not 0 < len(html) <= 1_400_000
            or not isinstance(parent, dict) or type(year) is not int
            or year not in (2027, 2028)):
        return False
    parent_name = parent.get("name")
    if not isinstance(parent_name, str) or not 8 <= len(parent_name) <= 180:
        return False
    tokens = re.findall(r"[a-z0-9]+", fold(parent_name))
    if not tokens or len("".join(tokens)) < 8:
        return False
    event_name = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, tokens))
        + r"(?![a-z0-9])"
    )
    parser = VisibleText()
    try:
        parser.feed(html)
        parser.close()
        visible = " ".join(fold(" ".join(parser.parts)).split())
    except (TypeError, ValueError, UnicodeError):
        return False
    if (not event_name.search(visible)
            or re.search(r"\b(?:festival|fest)\b", visible) is None
            and "fest" not in fold(parent_name)
            or CANCEL.search(visible)):
        return False
    # Do not cherry-pick a year without dates when the page contains actual
    # 2027 dates for *any* event. Investigate rather than publishing a false
    # 'dates unknown' item. Current dated publisher has priority.
    if any(explicit_ranges(visible, year)):
        return False
    year_phrase = re.compile(
        FUTURE_ANNOUNCEMENT.pattern.format(year=year), re.IGNORECASE
    )
    positives = list(year_phrase.finditer(visible))
    names = list(event_name.finditer(visible))
    if not positives or not names:
        return False
    return any(
        abs(phrase.start() - found.start()) <= 1400
        for phrase in positives for found in names[:80]
    )


def private_proposal(parent, year, today):
    """Construct strictly minimal, NON-publishing research proposal."""
    identity = pinned_parent_identity(parent)
    if (identity is None or parent.get("lastKnownYear") != identity[1]
            or type(year) is not int or year not in (2027, 2028)
            or year <= identity[1]
            or not isinstance(today, date)
            or not today.year <= year):
        return None
    name = str(parent.get("name") or "").strip() + " " + str(year)
    site = parent.get("officialSite")
    if (not isinstance(site, str) or not site.startswith("https://")
            or not 8 <= len(name) <= 180):
        return None
    return {
        "slug": identity[0] + "-" + str(year), "name": name,
        "startDate": None, "endDate": None,
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Dates à venir",
        "officialSite": site, "source": site,
        "lastVerified": today.isoformat(), "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE,
        "originSlug": parent["slug"], "evidence": [site],
        "verified_at": today.isoformat(),
    }


def validate_verified_row(proposal, archived, official_html, today):
    """Publisher gate: independently supplied official homepage, fail closed."""
    if (not isinstance(proposal, dict) or not isinstance(archived, dict)
            or not isinstance(official_html, str)
            or set(proposal) != ROW_KEYS | PRIVATE_KEYS
            or proposal.get("proofMode") != PROOF_MODE):
        return None
    now = iso_day(today)
    checked = iso_day(proposal.get("lastVerified"))
    parent_end = iso_day(archived.get("endDate"))
    proposed_title = proposal.get("name")
    identity = pinned_parent_identity(archived)
    if (now is None or checked is None or parent_end is None
            or identity is None or type(archived.get("lastKnownYear")) is not int
            or archived["lastKnownYear"] != identity[1]
            or not parent_end < now
            or not checked <= now
            or proposal.get("verified_at") != proposal["lastVerified"]
            or not isinstance(proposed_title, str)):
        return None
    slug_match = re.fullmatch(r"(.+)-(20[2-4][0-9])", str(proposal.get("slug")))
    if not slug_match:
        return None
    year = int(slug_match.group(2))
    expected = private_proposal(archived, year, checked)
    if (expected is None or year < now.year or year > now.year + 2
            or slug_match.group(1) != identity[0]
            or proposal.get("originSlug") != archived.get("slug")
            or edition_name(proposed_title) != edition_name(archived.get("name"))
            or proposal != expected
            or not visible_future_edition_without_dates(
                official_html, archived, year)):
        return None
    safe = {key: proposal[key] for key in ROW_KEYS}
    safe["verificationStatus"] = PUBLISHED_STATUS
    safe["sourceConfidence"] = PUBLISHED_CONFIDENCE
    safe["notes"] = PRIVATE_NOTES
    # No archive city, coordinates or historic lineup can cross this boundary.
    return safe


def conflicting_undated_edition(proposal, current, history):
    """No second row for an existing year, even without dated startDate."""
    match = re.fullmatch(r"(.+)-(20[2-4][0-9])", str(proposal.get("slug")))
    if not match:
        return True
    year = match.group(2)
    target = edition_name(proposal.get("name"))
    for row in list(current) + list(history):
        if not isinstance(row, dict):
            return True
        slug = row.get("slug")
        if slug == proposal["slug"]:
            return True
        name = row.get("name")
        if not isinstance(name, str):
            continue
        # A prior-year unsigned archival parent does NOT block the future
        # year. An existing edition of the same normalized name/year does.
        row_year = str(row.get("startDate") or "")[:4]
        years_in_title = re.findall(r"(?<!\d)20[2-4]\d(?!\d)", name)
        if (edition_name(name) == target
                and (row_year == year or year in years_in_title)):
            return True
    return False
