"""Renew historical festivals from independently re-fetched signed tourism pages.

Unlike discovery links, these source URLs were already reviewed and signed in
festival-history.json. The publisher never fetches a URL carried only by a
private proposal. It may admit a CURRENT edition announced by a tourism office
even if the organizer website still displays the previous edition.
Nothing from the prior edition's artist, venue, ticket or GPS data is copied.
"""
from __future__ import annotations

from datetime import date, timedelta
import re

from dns_pinned_https import safe_public_url
from source_qualification import classify, normalized
from grossesondes_institutional_edition import VisibleInstitutionHeadings
from grossesondes_official_html_edition import (
    MONTH_WORD, MONTHS, explicit_ranges, fold,
)
from grossesondes_structured_edition import (
    ROW_KEYS, PRIVATE_KEYS, pinned_parent_identity,
    no_same_edition_jsonld_contradiction,
)

PROOF_MODE = "signed-tourism-renewal.v1"
DAILY_PROBES = 4
# A bounded catch-up after a trusted code push may recheck all currently
# signed historical tourism references, without admitting new network roots.
MAX_PROBES = 20
MAX_HTML = 650_000
REVIEW_MARKERS = (
    "office de tourisme", "tourisme", "mairie", "collectivite",
    "institutionnel", "institutionnelle", "agglomeration",
)
MUSIC_STYLES = re.compile(
    r"\b(?:metal|rock|punk|hardcore|stoner|doom|sludge|grindcore)\b")
SCHEDULE_DAY = re.compile(
    r"\b(?:le|du|au)\s+([0-3]?\d)\s+(" + MONTH_WORD + r")\b")
TWO_DAYS = re.compile(r"\bpass\s*(?:2|deux)\s*jours?\b")


def signed_tourism_urls(parent):
    """Only previously signed historical URLs, never discovered/private hosts."""
    if not isinstance(parent, dict):
        return []
    evidence = normalized(parent.get("sourceConfidence", ""))
    if (not any(word in evidence for word in REVIEW_MARKERS)
            or not MUSIC_STYLES.search(normalized(parent.get("styles", "")))):
        return []
    candidates = parent.get("auditSources")
    if not isinstance(candidates, list) or len(candidates) > 30:
        return []
    accepted = []
    for url in candidates:
        if not isinstance(url, str) or len(url) > 500:
            continue
        if safe_public_url(url) != url:
            continue
        role = classify(url)
        if role in ("MEDIA", "SOCIAL", "TICKETING", "THIRD_PARTY",
                    "VENUE", "ORGANIZER_CANDIDATE"):
            continue
        # The signed editorial record specifically established tourism/
        # civic attribution. A merely unknown hostname cannot promote itself.
        if url not in accepted:
            accepted.append(url)
    return sorted(accepted)


def candidates_from_signed_history(history, published, today, limit=DAILY_PROBES,
                                   tick=0):
    """Bounded deterministic rotation; signed historical data is the sole seed."""
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or not isinstance(published, dict)
            or published.get("schema") != 1
            or not isinstance(published.get("festivals"), list)
            or type(limit) is not int or not 0 <= limit <= MAX_PROBES
            or type(tick) is not int or tick < 0):
        raise ValueError("Invalid signed tourism renewal input")
    current = date.fromisoformat(today)
    published_slugs = {r.get("slug") for r in published["festivals"]
                       if isinstance(r, dict)}
    choices = []
    for parent in history["knownFestivals"]:
        identity = pinned_parent_identity(parent) if isinstance(parent, dict) else None
        if identity is None or not isinstance(parent.get("name"), str):
            continue
        name = parent["name"].strip()
        if (not 8 <= len(name) <= 160
                or re.search(r"\b20[2-4]\d\b", name)):
            continue
        base, old_year = identity
        if (parent.get("lastKnownYear") != old_year
                or old_year >= current.year + 2):
            continue
        year = max(current.year + 1, old_year + 1)
        if year > current.year + 2 or base + "-" + str(year) in published_slugs:
            continue
        urls = signed_tourism_urls(parent)
        if urls:
            # One source per historical festival per run. Several signed
            # institutional citations cannot create duplicate additions;
            # rotate their alternatives instead of privileging one forever.
            choices.append((parent, urls[tick % len(urls)], year))
    choices.sort(key=lambda row: (row[0]["slug"], row[1]))
    if not choices or not limit:
        return []
    # At most the bounded per-run budget, drawn exclusively from signed
    # historical references. Daily passes remain limited to four.
    start = (tick * limit) % len(choices)
    return [choices[(start + i) % len(choices)]
            for i in range(min(limit, len(choices)))]


def current_edition_dates(html, parent, year):
    """Visible exact identity + dated future edition + complete date section.

    The opening teaser on an institutional page can display only the first day.
    When a dedicated Date section lists two or more days, use those explicit
    days rather than silently publishing an incomplete one-day festival.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= MAX_HTML
            or type(year) is not int or not isinstance(parent, dict)):
        return None
    base = normalized(parent.get("name", ""))
    if len(base) < 8:
        return None
    parser = VisibleInstitutionHeadings()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return None
    headings = [(normalized(h), start) for h, start in
                zip(parser.headings, parser.heading_starts)]
    title_positions = [n for n, (name, _) in enumerate(headings)
                       if name in (base, base + " " + str(year))]
    if len(title_positions) != 1:
        return None
    pos = title_positions[0]
    section = fold(" ".join(parser.parts[headings[pos][1]:]))
    visible_ranges = {(a, b) for _, _, a, b
                      in explicit_ranges(section, year)}
    if not visible_ranges:
        return None
    # The year's date must belong to the heading's nearby CURRENT edition,
    # not to an unrelated recommendation or an old footer article.
    if not any(start.year == year for start, end in visible_ranges):
        return None
    first_dated = min(
        m.start() for m in re.finditer(r"\b" + str(year) + r"\b", section))
    if first_dated > 850:
        return None
    date_sections = []
    for index, (heading, offset) in enumerate(headings):
        if index <= pos or heading not in ("date", "dates", "horaires et dates"):
            continue
        end = headings[index + 1][1] if index + 1 < len(headings) else len(parser.parts)
        section_words = fold(" ".join(parser.parts[offset:end]))
        days = []
        for m in SCHEDULE_DAY.finditer(section_words):
            try:
                day = date(year, MONTHS[fold(m.group(2))], int(m.group(1)))
            except (ValueError, KeyError):
                return None
            days.append(day)
        if days:
            date_sections.append(sorted(set(days)))
    if len(date_sections) > 1:
        return None
    if date_sections:
        schedule = date_sections[0]
        if (not 1 <= len(schedule) <= 8
                or (schedule[-1] - schedule[0]).days != len(schedule) - 1
                or not any(a <= schedule[0] <= b for a, b in visible_ranges)):
            return None
        start, end = schedule[0], schedule[-1]
        # A first-day teaser plus an advertised two-day pass is not an
        # independently proven single-day edition.
        if start == end and TWO_DAYS.search(section):
            return None
        # Any other fully specified date range must be contained in this
        # explicit schedule, not silently accepted as a contradiction.
        if any(a < start or b > end for a, b in visible_ranges):
            return None
    else:
        if len(visible_ranges) != 1:
            return None
        start, end = next(iter(visible_ranges))
        if start == end and TWO_DAYS.search(section):
            return None
    if (start.year != year or end.year != year or
            (end - start).days > 7 or not start <= end):
        return None
    if not no_same_edition_jsonld_contradiction(
            html, parent["name"].strip() + " " + str(year), start, end):
        return None
    if re.search(r"\b(?:annule|annulee|reportee|reporte|cancelled|postponed)\b",
                 section[:1300]):
        return None
    return start, end


def private_proposal(parent, url, year, html, today):
    """Generate a minimal current-edition proposal from signed provenance."""
    if (not isinstance(parent, dict) or url not in signed_tourism_urls(parent)
            or type(year) is not int or not isinstance(today, str)):
        return None
    identity = pinned_parent_identity(parent)
    if identity is None or parent.get("lastKnownYear") != identity[1]:
        return None
    checked = date.fromisoformat(today)
    if not checked.year <= year <= checked.year + 2 or year <= identity[1]:
        return None
    dates = current_edition_dates(html, parent, year)
    if dates is None or dates[0] < checked:
        return None
    title = parent["name"].strip() + " " + str(year)
    proposal = {
        "slug": identity[0] + "-" + str(year), "name": title,
        "startDate": dates[0].isoformat(), "endDate": dates[1].isoformat(),
        "city": None, "department": None, "region": None,
        "venue": None, "lat": None, "lon": None,
        "showOnMap": False, "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Annoncé", "officialSite": url, "source": url,
        "lastVerified": today,
        "notes": ("Édition annoncée sur une fiche touristique signée ; "
                  "artistes, tarifs, lieu et coordonnées à confirmer."),
        "verificationStatus": "Date institutionnelle à revérifier par le Publisher",
        "sourceConfidence": "Agenda touristique historique signé (preuve privée)",
        "proofMode": PROOF_MODE, "originSlug": parent["slug"],
        "evidence": [url], "verified_at": today,
    }
    return proposal


def validate_verified_row(proposal, parent, html, today):
    """Publisher re-proves all event facts from the signed historical URL."""
    if not isinstance(proposal, dict) or set(proposal) != ROW_KEYS | PRIVATE_KEYS:
        return None
    if (proposal.get("proofMode") != PROOF_MODE or not isinstance(parent, dict)
            or proposal.get("originSlug") != parent.get("slug")):
        return None
    url = proposal.get("source")
    if url != proposal.get("officialSite") or proposal.get("evidence") != [url]:
        return None
    try:
        verified_date = date.fromisoformat(proposal["verified_at"])
        now = date.fromisoformat(today)
    except (ValueError, TypeError):
        return None
    if (verified_date > now or (now - verified_date) > timedelta(days=7)
            or proposal["lastVerified"] != proposal["verified_at"]):
        return None
    year = int(proposal["startDate"][:4]) if isinstance(proposal.get("startDate"), str) else 0
    recreated = private_proposal(parent, url, year, html, today)
    if recreated is None:
        return None
    for k in ROW_KEYS | PRIVATE_KEYS:
        if k not in ("lastVerified", "verified_at") and proposal[k] != recreated[k]:
            return None
    signed = {key: recreated[key] for key in ROW_KEYS}
    signed["verificationStatus"] = "Édition touristique revérifiée indépendamment"
    signed["sourceConfidence"] = "Office de tourisme historiquement signé + relecture Publisher"
    signed["notes"] = ("Dates de l'édition revérifiées sur une fiche touristique "
                       "historique signée. Aucun artiste, tarif, lieu exact ni "
                       "coordonnée de l'édition passée n'est hérité.")
    return signed
