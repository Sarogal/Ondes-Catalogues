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

from grossesondes_official_html_edition import (
    VisibleText, fold, explicit_ranges, visible_official_edition,
    dominant_visible_range, administrative_calendar_dates,
)
from grossesondes_structured_edition import (
    ROW_KEYS, PRIVATE_KEYS, no_same_edition_jsonld_contradiction, conflicts_with_existing,
)
from national_detail_qualification import _seen_again
from national_discovery_queue import _safe_origin_link
from official_watch import get_page, permitted_url
from regional_agenda_pagination import canonical_page_url
from regional_festival_discovery import (
    APPROVED, candidate_links, INDEX_MUSIC_PROOF_SIGNALS,
)
from source_qualification import normalized

PROOF_MODE = "institutional-visible-edition.v1"
PRIVATE_NOTES = ("Dates mentionnées sur un agenda institutionnel ; lieu, "
                 "artistes, tarif et coordonnées non vérifiés.")
PRIVATE_STATUS = "Dates institutionnelles à revérifier indépendamment avant publication"
PRIVATE_CONFIDENCE = "Agenda institutionnel (observation privée)"
PUBLISHED_STATUS = "Dates revérifiées sur agenda institutionnel ; lieu et coordonnées non confirmés"
PUBLISHED_CONFIDENCE = "Agenda institutionnel (fiche et index relus indépendamment)"


def institutional_date(html, title, year):
    """Require ONE noncontradictory maximal visible range near the title.

    Independent pure HTML parser: does not import the archived intake or
    cloud stage modules, avoiding circular dependencies with the publisher.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return None
    parser = VisibleText()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    content = " ".join(fold(" ".join(parser.parts)).split())
    # An explicit ticket-sale OPENING day in its own visible paragraph
    # is an administrative milestone, not a second date of this edition.
    # Never ignore any multi-day, mixed, festival-labelled or cancelled claim.
    excluded = administrative_calendar_dates(html, title, year)
    unique = {(start, end) for _a, _b, start, end
              in explicit_ranges(content, year)
              if (start, end) not in excluded}
    dates = dominant_visible_range(unique)
    if dates is None:
        return None
    start, end = dates
    if not visible_official_edition(html, title, start, end):
        return None
    return start, end


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
    try:
        current_year = date.fromisoformat(today).year
    except (TypeError, ValueError):
        return None
    if not current_year <= year <= current_year + 2:
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
            or first.year != spec["year"] or last.year != spec["year"]
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


# Only the immutable institution's own event-detail BODY may establish a
# theme when a visible index title ("Festival des Rivages 2027") omits it.
# Bare "hardcore" is ambiguous with electronic music and is not sufficient.
FESTIVAL_MUSIC_CONTEXT = re.compile(
    r"\b(?:festival|programmation|concerts?|musique|genres?|styles?)"
    r"\s+(?:(?:de|du|des|en|a|aux)\s+)?"
    r"(?:heavy metal|black metal|death metal|thrash metal|metalcore|"
    r"deathcore|grindcore|post metal|post rock|hard rock|rock alternatif|"
    r"punk rock|hardcore punk|metal|rock|punk|stoner|doom|sludge|thrash)\b"
)
TOURING_SHOW = re.compile(
    r"\b(?:tournee itinerante|date[s]? de la tournee|"
    r"concerts? de la tournee|concert tour|tour de concerts?|"
    r"tournee de \d+ concerts?)\b"
)


class VisibleInstitutionHeadings(VisibleText):
    """Capture only explicitly VISIBLE h1/h2 main-event labels.

    A generic "Site officiel du Festival X" footer or a hidden annotation
    must never authorize an unrelated index event's organizer website.
    """
    def __init__(self):
        super().__init__()
        self.headings = []
        self.heading_starts = []
        self.heading_tag = None
        self.heading_words = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in ("h1", "h2") and not self.hidden():
            self.heading_tag = tag
            self.heading_starts.append(len(self.parts))
            self.heading_words = []

    def handle_data(self, data):
        super().handle_data(data)
        if self.heading_tag is not None and not self.hidden():
            self.heading_words.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            if not self.hidden():
                self.headings.append(" ".join(self.heading_words))
            self.heading_tag = None
            self.heading_words = []
        super().handle_endtag(tag)


def independent_institutional_music_genre(detail_html, edition_title, year):
    """Fresh visible, exact-edition theme, NOT OpenData or a private genre.

    Used only AFTER an approved index was fetched again and an EXACT visible
    title+same-host link was found. Reject hidden text, generic genre words
    disconnected from the edition, electronic 'hardcore' alone and tours.
    This is never proof of dates, venue, ownership or publisher independence.
    """
    if (not isinstance(detail_html, str) or not 0 < len(detail_html) <= 650_000
            or not isinstance(edition_title, str)
            or type(year) is not int
            or not edition_title.strip().endswith(" " + str(year))):
        return False
    parser = VisibleInstitutionHeadings()
    try:
        parser.feed(detail_html)
        parser.close()
    except (TypeError, UnicodeError, ValueError):
        return False
    label = normalized(edition_title)
    if len(label) < 12:
        return False
    matcher = re.compile(r"(?<![a-z0-9])" + re.escape(label)
                         + r"(?![a-z0-9])")
    # Every candidate genre must belong to the SAME visible event heading's
    # own section, ending before the next h1/h2. Nearby OTHER event headings
    # can never lend a theme to an unrelated festival. Section boundaries
    # come from the parser's part indices, NOT page-provided separator text.
    for index, (heading, start) in enumerate(zip(
            parser.headings, parser.heading_starts)):
        if normalized(heading) != label:
            continue
        end = (parser.heading_starts[index + 1]
               if index + 1 < len(parser.heading_starts) else len(parser.parts))
        section = normalized(" ".join(parser.parts[start:end]))
        for reference in list(matcher.finditer(section))[:5]:
            nearby = section[max(0, reference.start() - 110):
                             reference.end() + 320]
            if (TOURING_SHOW.search(nearby)
                    or re.search(r"\b(?:annule|annulee|reportee|reporte)\b",
                                 nearby)):
                return False
            if FESTIVAL_MUSIC_CONTEXT.search(nearby):
                return True
    return False


def independently_fetch(proposal, today, fetch=get_page):
    """Return HTML only if a fresh, approved live index proves the exact link.

    A proposed URL is NEVER fetched until the live index establishes the
    exact visible title and same-host link. If this label omits the genre,
    the independently fetched trusted institutional DETAIL must visibly prove
    a rock/metal/punk festival theme before any admission can proceed.
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
        theme_on_index = any(
            x.get("candidate_url") == spec["url"]
            and normalized(x.get("title")) == normalized(spec["title"])
            and x.get("signal") in INDEX_MUSIC_PROOF_SIGNALS
            for x in matches)
        # The new fallback cannot use a self-declared OpenData genre. Fetch
        # only the EXACT detail whose anchor just appeared on the trusted index.
        html = fetch(spec["url"])
        if (not theme_on_index and not independent_institutional_music_genre(
                html, spec["title"], spec["year"])):
            return None
        return html
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
        dates = institutional_date(html, proposal["name"], spec["year"])
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
