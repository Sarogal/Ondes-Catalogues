"""Observe CURRENT-edition commune announcements without inventing a venue.

Official organizer homepage and at most two SAME-HOST current-edition/visit
pages. A city is only a first-party, edition-dated claim; no coordinates
or map pin exist here. Re-observe on separate days; public publisher must
independently re-fetch official proof and the national commune registry.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dns_pinned_https import fetch_public_html, safe_public_url
from future_geo_preflight import (
    _VisibleOrganizerLinks, _matching_event, _name, _country,
    safe_fetch_failure_code,
    _atomic, eligible, official_access_links,
)
SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_structured_roster import (
    JsonLD, SENSITIVE_STATUSES, edition_name, iso_day, walk,
)
from grossesondes_official_html_edition import (
    CANCEL, VisibleText, VisibleParagraphs, MONTHS as OFFICIAL_MONTHS,
    dominant_visible_range, explicit_ranges, fold,
)

SCHEMA = "grossesondes.future-festival-city-private.v1"
STATE_KEY = "future_edition_city_observations_private"
CURSOR_KEY = "future_edition_city_rotation_cursor"
MAX_INTERNAL_PAGES = 2
# 13 currently eligible editions; 8 per run covers them across both daily cycles.
# Keep a bounded, auditable budget; geo research retains its own cap of four.
MAX_CHECKS = 8
MAX_NESTED_NEWS_PAGES = 2
CITY_PATTERN = re.compile(
    r"\b(?:à|au|in|at)\s+([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+"
    r"(?:[-'][A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*"
    r"(?:\s+[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+(?:[-'][A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*){0,3})"
)
EXCLUDE = re.compile(r"(?:202[0-6]|201\d|archive|photo|contact|cookie|mentions|"
                     r"billet|ticket|shop|boutique|privacy|partenaire)", re.I)
CURRENT = re.compile(r"(?:2027|2028|2029|20[3-4]\d|edition|nouvelle|new|"
                     r"actu|news|actualite|nouveaute|dates)", re.I)


def _normal(value):
    return "".join(re.findall(r"[a-z0-9]+", fold(value)))


def _city_jsonld(html, row):
    parser = JsonLD()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if not start or not end:
        return None
    facts = set()
    for document in parser.documents[:30]:
        for event in walk(document):
            if not _matching_event(event, row):
                continue
            if (iso_day(event.get("startDate")) != start
                    or iso_day(event.get("endDate")) != end
                    or str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
                       in SENSITIVE_STATUSES):
                return False
            location = event.get("location")
            if not isinstance(location, dict):
                return None
            raw_types = location.get("@type", [])
            types = raw_types if isinstance(raw_types, list) else [raw_types]
            if "place" not in {str(t).rsplit("/", 1)[-1].casefold() for t in types}:
                return False
            address = location.get("address")
            if not isinstance(address, dict):
                return None
            city = _name(address.get("addressLocality"))
            # Require either explicit FR or pre-registered same-city context.
            if (city is None or
                    (address.get("addressCountry") not in (None, "")
                     and _country(address) != "FR") or
                    (_country(address) != "FR"
                     and _normal(city) != _normal(row.get("city")))):
                return False
            facts.add(city)
    return next(iter(facts)) if len(facts) == 1 else (False if facts else None)



def _title_identifies_official_festival(html, name):
    """Title confirms ONLY the host's festival identity, never dates or town.

    Some official festival websites display their name solely as an image logo
    rather than visible text. A stale SEO year in <title> must NOT be borrowed
    as evidence for this year's dates or municipality.
    """
    title = _EditionTitle()
    try:
        title.feed(html)
        title.close()
    except (ValueError, TypeError, UnicodeError):
        return False
    raw = " ".join(" ".join(title.parts).split())
    return 8 <= len(raw) <= 250 and name.search(fold(raw)) is not None


def _city_visible(html, row):
    """A named dated edition, or a first-party edition/date/city hero.

    The title may be in the official site's heading/identity while the
    current-year date and city are in a separate hero caption. The latter
    MUST explicitly say "édition" and put the location AFTER the current
    dates in its own visible block. A bare historic venue, organizer address,
    or undated contact/footer does not establish a future location.
    """
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or start.year != end.year:
        return None
    words = re.findall(r"[a-z0-9]+",
                       re.sub(r"\b20[2-4]\d\b", "", fold(row.get("name", ""))))
    if len("".join(words)) < 8:
        return None
    name = re.compile(r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
                      + r"(?![a-z0-9])")
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    blocks = [raw for raw in
              " ".join(parser.parts).split(VisibleParagraphs.SEP)
              if 0 < len(raw) <= 1100]
    # Another event's generic date + city can never be attributed to the
    # published festival unless this SAME official page names its festival.
    branded = (_title_identifies_official_festival(html, name) or
               any(name.search(" ".join(fold(raw).split())) for raw in blocks))
    facts = set()
    for raw in blocks:
        paragraph = " ".join(fold(raw).split())
        if (CANCEL.search(paragraph)
                or {int(y) for y in re.findall(r"(?<!\d)20[2-4]\d(?!\d)", raw)}
                   != {start.year}):
            continue
        ranges = {(a, b) for _, _, a, b
                  in explicit_ranges(paragraph, start.year)}
        if dominant_visible_range(ranges) != (start, end):
            continue
        named = name.search(paragraph) is not None
        hero = (not named and branded
                and re.search(r"\bedition\b", paragraph) is not None)
        # Current official festival pages can print a unique EXACT date span
        # and "Légna (39)" in the same hero <p>, while the branded festival
        # identity is in a different heading. The already signed first-party
        # root supplies provenance, not the identity of an unrelated event.
        # Requiring a printed department after the year prevents accepting
        # bare generic town words or an archive/footer contact address.
        dated_locality = (not named and not hero and branded
                          and row.get("startDate") is not None
                          and row.get("endDate") is not None)
        if dated_locality:
            for match in re.finditer(
                    rf"(?<!\d){start.year}(?!\d)\s*"
                    r"(?:[·•:–—\-]\s*)?"
                    r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
                    r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,2})"
                    r"\s*\((\d{2,3}|2[AB])\)",
                    raw):
                candidate, department = match.group(1), match.group(2)
                # Two different locality/dept annotations in the same
                # date hero are contradictory: never pick the first match.
                locality_count = len(re.findall(
                    r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
                    r"\s*\((?:\d{2,3}|2[AB])\)", raw))
                if (locality_count != 1
                        or row.get("department") not in (None, "", department)
                        or re.search(
                            r"\b(?:Festival|France|Vente|Billetterie|"
                            r"Programmation)\b", candidate)):
                    continue
                city = _name(candidate)
                if city:
                    facts.add(city)
        # A first-party current-edition practical-info block may state the
        # exact signed dates and a single "dans la salle ... à Commune" even
        # when the festival name appears only in the homepage heading.
        # Do not borrow a historic venue: the date interval must already
        # match this SAME visible paragraph; two place claims are ambiguous.
        dated_visit = (not named and not hero and branded
                       and re.search(r"\brendez[\W_]+vous\b", paragraph)
                       and re.search(r"\bdans\s+la\s+salle\b", paragraph))
        if dated_visit:
            towns = [city for match in CITY_PATTERN.finditer(raw)
                     if (city := _name(match.group(1))) is not None]
            if len(towns) == 1 and not re.search(
                    r"\b(?:Festival|France|Vente|Billetterie|"
                    r"Programmation)\b", towns[0]):
                facts.add(towns[0])
        if not (named or hero):
            continue
        # Existing strict path: exact named festival, current dates and city
        # in a single visible block.
        if named:
            for match in CITY_PATTERN.finditer(raw):
                city = _name(match.group(1))
                if city and not re.search(
                        r"\b(?:Festival|France|Parisien|Vente|Billetterie)\b",
                        city):
                    facts.add(city)
        # Official edition hero: "4e édition · 23 & 24 avril 2027 · Aix-en-
        # Provence". The page separately names the festival. Never use a
        # locality preceding the edition date or a second, undated paragraph.
        if hero:
            pieces = re.split(r"[·•]", raw)
            for i, piece in enumerate(pieces[:-1]):
                if not re.search(
                        rf"(?<!\d){start.year}(?!\d)", piece):
                    continue
                for location in pieces[i + 1:i + 3]:
                    candidate = location.strip()
                    if (not re.fullmatch(
                            r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-–]+"
                            r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-–]+){0,3}",
                            candidate)
                            or re.search(r"\d", candidate)):
                        continue
                    city = _name(candidate)
                    if city and city not in ("France", "Festival",
                                             "Programmation", "Billetterie"):
                        facts.add(city)
    return next(iter(facts)) if len(facts) == 1 else None

def undated_future_year(row, today=None):
    """Only signed, explicitly undated *future* festival edition identities.

    Never infer a new year or municipality from the archived site alone.
    Called on already-published rows, not on arbitrary private candidates.
    """
    if (not isinstance(row, dict)
            or row.get("startDate") is not None
            or row.get("endDate") is not None
            or row.get("status") != "Dates à venir"
            or row.get("showOnMap") is True
            or row.get("lat") is not None or row.get("lon") is not None):
        return None
    slug, title = row.get("slug"), row.get("name")
    if not isinstance(slug, str) or not isinstance(title, str):
        return None
    match = re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-(20[2-4][0-9])", slug)
    suffix = re.search(r"(?<![0-9])20[2-4][0-9]$", title)
    if match is None or suffix is None or suffix.group() != match.group(1):
        return None
    year = int(match.group(1))
    if today is not None:
        current = date.fromisoformat(today).year
        if not current < year <= current + 2:
            return None
    return year



class _VisibleEditionSections(VisibleParagraphs):
    """Isolate visible blocks of an edition hero within its own section.

    Official sites frequently use <div> for town/department stats alongside
    <p> for the next-edition headline. Merely inserting a space between divs
    merged two distinct fields into one unparseable 'town department' string.
    The additional separators apply only to this strict 4-field proof parser,
    not to the rest of the site's date or identity extractors.
    """
    SECTION = "\x1e"

    def handle_starttag(self, tag, attrs):
        if not self.hidden():
            if tag == "section":
                self.parts.append(self.SECTION)
            elif tag == "div":
                self.parts.append(self.SEP)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if not self.hidden():
            if tag == "section":
                self.parts.append(self.SECTION)
            elif tag == "div":
                self.parts.append(self.SEP)
        super().handle_endtag(tag)


def _section_undated_city(html, row, year, name):
    """Current-edition banner + festival genre + town + department, in one section.

    Stronger than a loose homepage contact address: the municipality and its
    département label must follow this edition's own explicit future banner
    inside ONE visible section. Government resolves the label independently.
    """
    parser = _VisibleEditionSections()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    if (not name.search(" ".join(fold(" ".join(parser.parts)).split()))
            and not _title_identifies_official_festival(html, name)):
        return None
    found = set()
    heading = re.compile(
        rf"\bedition(?:\s+[0-9]{{1,2}})?\s*(?:[·—–-]\s*)?"
        rf"(?:(?:ete|hiver|printemps|automne)\s+)?{year}\b")
    locality = re.compile(
        r"[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
        r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,3}")
    for chunk in " ".join(parser.parts).split(parser.SECTION):
        parts = [p.strip() for p in chunk.split(VisibleParagraphs.SEP) if p.strip()]
        if not 4 <= len(parts) <= 40:
            continue
        for i in range(len(parts) - 3):
            # Keep edition, genre, town and department adjacent. HTML sites
            # sometimes wrap their 2027 hero and a 2026 photo recap in the
            # same outer section; that unrelated old year is NOT proof about
            # the current edition. However an old year inside the exact
            # four-element claim still vetoes the whole candidate.
            local = parts[i:i + 4]
            folded = " ".join(fold(" ".join(local)).split())
            years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", folded))
            if (years != {str(year)} or CANCEL.search(folded)
                    or any(explicit_ranges(folded, year))
                    or not heading.search(" ".join(fold(parts[i]).split()))):
                continue
            genre, raw_city, raw_dept = local[1:]
            if not re.search(r"\bfestival\b", fold(genre)):
                continue
            if not locality.fullmatch(raw_city) or not locality.fullmatch(raw_dept):
                continue
            # Reject an extra adjacent place-like field. For instance, a
            # misleading "Town A / Town B / Département" sequence must not
            # turn Town B into the department of Town A. This also protects
            # generic nested div grids without hardcoding French communes.
            if (i + 4 < len(parts)
                    and locality.fullmatch(parts[i + 4])):
                continue
            city, department = _name(raw_city), _name(raw_dept)
            if (not city or not department or
                    _normal(city) in {"france", "festival", "billetterie",
                                      "programmation", "prochainement"}):
                continue
            found.add((city, department))
    return next(iter(found)) if len(found) == 1 else None


def _city_visible_undated(html, row, year):
    """Same-block organizer claim: edition identity + future year + city.

    Dates are still unknown. 'Festival X 2026 at City Y' somewhere else on the
    website does not support placing its 2027 edition in that municipality.
    """
    tokens = re.findall(r"[a-z0-9]+", re.sub(
        r"\b20[2-4][0-9]\b", "", fold(row.get("name", ""))))
    if len("".join(tokens)) < 8:
        return None
    name = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, tokens))
        + r"(?![a-z0-9])"
    )
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return None
    cities = set()
    for raw in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        if not 0 < len(raw) <= 1100:
            continue
        paragraph = " ".join(fold(raw).split())
        years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", paragraph))
        if (not name.search(paragraph) or years != {str(year)}
                or CANCEL.search(paragraph)
                or not re.search(
                    r"\b(?:edition|rendez[\W_]+vous|revient|retour)\b",
                    paragraph)
                or re.search(
                    r"\b(?:preparer?|preparation|projet|eventuel|"
                    r"incertain|peut[\W_]+etre|sous[\W_]+reserve|"
                    r"cagnotte|financement|tournee|tour)\b",
                    paragraph)
                or any(explicit_ranges(paragraph, year))):
            continue
        for matched in CITY_PATTERN.finditer(raw):
            city = _name(matched.group(1))
            if city and not re.search(
                    r"\b(?:Festival|France|Parisien|Vente|Billetterie)\b",
                    city):
                cities.add(city)
    section = _section_undated_city(html, row, year, name)
    if len(cities) > 1 or (cities and section and
                           _normal(next(iter(cities))) != _normal(section[0])):
        return None
    return section if section is not None else (
        next(iter(cities)) if len(cities) == 1 else None)


def eligible_undated(calendar, today):
    if not isinstance(calendar, dict) or not isinstance(calendar.get("festivals"), list):
        raise ValueError("Invalid signed catalogue")
    rows = []
    for item in calendar["festivals"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid signed row")
        if undated_future_year(item, today) is not None:
            rows.append(item)
    return rows


class _EditionTitle(HTMLParser):
    """Read only the actual first-party HTML title, never scripts or metadata."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)


def _city_from_dated_title(html, row):
    """Exact signed edition + dates + commune in one first-party page title.

    Example (not a named-site rule):
    Festival X - 23 24 25 juillet 2027 - Commune (57)
    A loose footer, historic edition or unrelated location is insufficient.
    """
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or start.year != end.year or start.month != end.month:
        return None
    parsed = _EditionTitle()
    try:
        parsed.feed(html)
        parsed.close()
    except (TypeError, ValueError, UnicodeError):
        return None
    title = " ".join(" ".join(parsed.parts).split())
    if not 10 <= len(title) <= 250:
        return None
    normalized = fold(title)
    brand = fold(re.sub(r"\b20[2-4]\d\b", "", row.get("name", ""))).strip()
    if len(brand.replace(" ", "")) < 8 or not re.search(
            r"(?<![a-z0-9])" + r"\s+".join(map(re.escape, brand.split()))
            + r"(?![a-z0-9])", normalized):
        return None
    years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", normalized))
    if years != {str(start.year)}:
        return None
    months = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
              "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
    month = months[start.month - 1]
    match = re.search(
        r"((?:\b\d{1,2}\b\s+(?:(?:au|et)\s+)?){1,8})"
        + month + r"\s+" + str(start.year) + r"\b",
        normalized)
    if match is None:
        return None
    days = [int(n) for n in re.findall(r"\b\d{1,2}\b", match.group(1))]
    if not days or days[0] != start.day or days[-1] != end.day:
        return None
    tail = re.search(
        rf"\b{start.year}\b\s*[-–|·:]\s*"
        r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\- ]{1,80}?)"
        r"(?:\s*\(\d{2,3}\))?\s*$", title)
    if tail is None:
        return None
    city = _name(tail.group(1).strip())
    if not city or city in ("France", "Festival", "Programmation", "Billetterie"):
        return None
    return city



def _current_edition_evergreen_commune(html, row):
    """Official dated homepage + explicit present-tense branded festival town.

    A current edition can be announced in a hero while the organizer describes
    the festival's permanent commune in its official overview. No inherited
    archive address is allowed: exact signed date and event identity must occur
    together near the top of this SAME first-party homepage, and the location
    sentence must independently name this same festival in present tense.
    """
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or start.year != end.year:
        return None
    words = re.findall(r"[a-z0-9]+", re.sub(
        r"\b20[2-4]\d\b", "", fold(row.get("name", ""))))
    if len("".join(words)) < 8:
        return None
    identity = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
        + r"(?![a-z0-9])")
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    blocks = [raw for raw in
              " ".join(parser.parts).split(VisibleParagraphs.SEP)
              if 0 < len(raw) <= 1100]
    # The event's branded hero must announce its OWN exact current interval.
    # Reject inconsistent 2027 ranges; a ticket-sale date is not event proof.
    date_blocks = []
    for i, raw in enumerate(blocks):
        folded = " ".join(fold(raw).split())
        ranges = {(a, b) for _, _, a, b in explicit_ranges(folded, start.year)}
        if not ranges:
            continue
        if CANCEL.search(folded) or dominant_visible_range(ranges) != (start, end):
            return None
        if (i < 6 and any(identity.search(" ".join(fold(x).split()))
                          for x in blocks[max(0, i - 2):i + 1])):
            date_blocks.append(i)
    if not date_blocks:
        return None
    # An old recap, organizer address, unrelated event or generic site
    # geography never qualifies. Require a current indicative festival
    # statement naming the exact brand and the town explicitly.
    facts = set()
    for raw in blocks:
        paragraph = " ".join(fold(raw).split())
        if (not identity.search(paragraph) or CANCEL.search(paragraph)
                or re.search(r"(?<!\d)20[2-4]\d(?!\d)", paragraph)
                or not re.search(
                    r"\b(?:se\s+deroule|aura\s+lieu|a\s+lieu)\s+a\b",
                    paragraph)):
            continue
        candidates = [city for match in CITY_PATTERN.finditer(raw)
                      if (city := _name(match.group(1))) is not None]
        if len(candidates) != 1:
            continue
        city = candidates[0]
        if _normal(city) not in {"france", "festival", "programmation",
                                 "billetterie", "prochainement"}:
            facts.add(city)
    return next(iter(facts)) if len(facts) == 1 else None



def _city_from_official_title_plus_named_current_dates(html, row):
    """A title identifying a festival's town plus a named current-date claim.

    Some official festival homepages use a site-wide SEO title saying that
    the festival takes place in Town (département), while their visible
    announcement identifies the next edition and exact dates. Neither the
    title alone nor an archive's dates can authorize the location.
    """
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or start.year != end.year:
        return None
    words = re.findall(r"[a-z0-9]+", re.sub(
        r"\b20[2-4]\d\b", "", fold(row.get("name", ""))))
    if len("".join(words)) < 8:
        return None
    identity = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
        + r"(?![a-z0-9])")
    title = _EditionTitle()
    parser = VisibleParagraphs()
    try:
        title.feed(html)
        title.close()
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    raw_title = " ".join(" ".join(title.parts).split())
    if (not 20 <= len(raw_title) <= 250
            or re.search(r"\bfestivals?\b", fold(raw_title)) is None
            or re.search(r"(?<!\d)20[2-4]\d(?!\d)", raw_title)):
        return None
    cities = set()
    for m in re.finditer(
            r"\bà\s+([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+"
            r"(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+){0,3})"
            r"\s*\((\d{2,3}|2[AB])(?:-[^)]{1,48})?\)", raw_title):
        city = _name(m.group(1))
        code = m.group(2)
        if city and row.get("department") in (None, "", code):
            cities.add(city)
    if len(cities) != 1:
        return None
    found = False
    for raw in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        if not 0 < len(raw) <= 1100:
            continue
        paragraph = " ".join(fold(raw).split())
        if not identity.search(paragraph):
            continue
        if (CANCEL.search(paragraph) or
                {int(x) for x in re.findall(r"(?<!\d)20[2-4]\d(?!\d)",
                                              paragraph)} != {start.year}):
            continue
        ranges = {(a, b) for _, _, a, b in
                  explicit_ranges(paragraph, start.year)}
        if ranges and dominant_visible_range(ranges) != (start, end):
            return None
        if dominant_visible_range(ranges) == (start, end):
            found = True
    return next(iter(cities)) if found else None


class _VisibleOfficialImageAlts(VisibleText):
    """Read only visible alt attributes; never load image URLs or other hosts."""
    def __init__(self):
        super().__init__()
        self.alts = []

    def handle_starttag(self, tag, attrs):
        if tag == "img" and not self.hidden() and len(self.alts) < 40:
            attributes = dict(attrs)
            style = fold(attributes.get("style") or "")
            if (not any(k in attributes for k in ("hidden",))
                    and attributes.get("aria-hidden") != "true"
                    and not re.search(
                        r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                        style)):
                alt = attributes.get("alt")
                if isinstance(alt, str) and 12 <= len(alt) <= 220:
                    self.alts.append(alt)
        super().handle_starttag(tag, attrs)


def _city_from_current_edition_image_alt(html, row):
    """An explicit exact-year, exact-date and single-town image description.

    First-party editors may use their current edition's main banner image
    with a complete textual alt while the homepage SEO title gives only an
    adjacent city. Never infer a town from an image file or a previous edition.
    """
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if (start is None or end is None or start.year != end.year
            or start.month != end.month):
        return None
    words = re.findall(
        r"[a-z0-9]+",
        re.sub(r"\b20[2-4]\d\b", "", fold(row.get("name", ""))))
    if len("".join(words)) < 8:
        return None
    name = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
        + r"(?![a-z0-9])")
    parser = _VisibleOfficialImageAlts()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return None
    date_location = re.compile(
        r"\b(?:le|les)\s+"
        r"(?P<days>[0-3]?\d(?:\s*(?:[,/&–—-]|\bet\b|\bau\b|\band\b)"
        r"\s*[0-3]?\d){0,6})"
        r"\s+(?P<month>[A-Za-zÀ-ÿ]+)\s+à\s+"
        r"(?P<city>[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’\- ]{1,75}?)"
        r"(?:\s*\((?P<dep>\d{2,3}|2[AB])\))?\s*$",
        re.IGNORECASE)
    towns = set()
    for alt in parser.alts:
        if not name.search(fold(alt)) or CANCEL.search(fold(alt)):
            continue
        years = re.findall(r"(?<!\d)20[2-4]\d(?!\d)", alt)
        if set(years) != {str(start.year)}:
            continue
        matched = date_location.search(alt)
        if matched is None:
            continue
        month = OFFICIAL_MONTHS.get(fold(matched.group("month")))
        days = [int(x) for x in re.findall(
            r"\b\d{1,2}\b", matched.group("days"))]
        if (month != start.month or not days
                or days[0] != start.day or days[-1] != end.day
                or (len(days) > 1 and
                    "au" not in fold(matched.group("days"))
                    and days != list(range(start.day, end.day + 1)))):
            continue
        city = _name(matched.group("city").strip())
        department = matched.group("dep")
        if (not city or
                row.get("department") not in (None, "", department)
                and department is not None):
            continue
        towns.add(city)
    return next(iter(towns)) if len(towns) == 1 else None


def _signed_tourism_current_postal_city(html, row):
    """Only an edition-dated postal commune beside a signed tourism event.

    Tourism providers often print the one-day teaser and a two-day schedule
    separately. Reprove the exact visible full current-edition dates first;
    never use the old archive's city, venue, department, or coordinates.
    A city here is only a proof candidate: the real publisher independently
    re-fetches the signed page and verifies the unique commune via the fixed
    government API before using a *commune-centre* map marker.
    """
    if (not isinstance(row, dict) or not isinstance(html, str)
            or row.get("sourceConfidence") !=
                "Office de tourisme historiquement signé + relecture Publisher"
            or row.get("source") != row.get("officialSite")
            or safe_public_url(row.get("officialSite")) is None):
        return None
    start = iso_day(row.get("startDate"))
    end = iso_day(row.get("endDate"))
    name = row.get("name")
    if (start is None or end is None or start.year != end.year
            or not isinstance(name, str)
            or not name.endswith(" " + str(start.year))
            or (end - start).days > 7):
        return None
    base = name[:-(len(str(start.year)) + 1)].strip()
    if len(_normal(base)) < 8:
        return None
    # The identical independent admission proof must be current on the
    # *live* tourist page. A JSON-LD or HTML contradiction remains a veto.
    from grossesondes_signed_institutional_renewal import current_edition_dates
    if current_edition_dates(html, {"name": base}, start.year) != (start, end):
        return None
    from grossesondes_institutional_edition import VisibleInstitutionHeadings
    parser = VisibleInstitutionHeadings()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    titles = [i for i, title in enumerate(parser.headings)
              if _normal(title) == _normal(base)]
    if len(titles) != 1:
        return None
    i = titles[0]
    begin = parser.heading_starts[i]
    end_offset = (parser.heading_starts[i + 1]
                  if i + 1 < len(parser.headings) else len(parser.parts))
    # Only the bounded event introduction, not the footer, other events, or
    # an unrelated geolocation widget on the same 100 kB tourist page.
    intro = " ".join(" ".join(parser.parts[begin:end_offset]).split())[:500]
    date_label = re.search(r"\b" + str(start.year) + r"\b", intro)
    if date_label is None:
        return None
    postcodes = []
    postal = re.compile(
        r"(?<!\d)(?:0[1-9]|[1-9][0-9])\d{3}\s+"
        r"([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'’ -]{2,65})")
    for match in postal.finditer(intro):
        # The postal town must describe THIS visible dated event, not a
        # neighbouring venue card or a historical office address.
        if not 0 <= match.start() - date_label.start() <= 200:
            continue
        town = re.sub(r"\s+", " ", match.group(1)).strip(" -'’")
        if not 3 <= len(town) <= 65 or not re.search(r"[A-ZÀ-ÖØ-Þ]{3}", town):
            continue
        postcodes.append(town.title())
    if len({_normal(city) for city in postcodes}) != 1:
        return None
    return postcodes[0]


def exact_edition_city(html, row):
    """One city of one 2027 edition, or nothing. Never infer from old years."""
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return None
    start = iso_day(row.get("startDate"))
    undated_year = undated_future_year(row)
    if start is None and undated_year is None:
        return None
    if start is not None and start.year not in range(2026, 2050):
        return None
    if undated_year is not None:
        clue = _city_visible_undated(html, row, undated_year)
        city = clue[0] if isinstance(clue, tuple) else clue
        if not city or (row.get("city")
                        and _normal(city) != _normal(row["city"])):
            return None
        proof = {"slug": row["slug"], "city": city, "source": row["officialSite"]}
        if isinstance(clue, tuple):
            proof["departmentLabel"] = clue[1]
        return proof
    structured = _city_jsonld(html, row)
    if structured is False:
        return None
    visible = _city_visible(html, row)
    title = _city_from_dated_title(html, row) if start is not None else None
    evergreen = _current_edition_evergreen_commune(html, row)
    title_place = _city_from_official_title_plus_named_current_dates(html, row)
    image_alt_place = _city_from_current_edition_image_alt(html, row)
    tourism_place = _signed_tourism_current_postal_city(html, row)
    evidence = [c for c in (structured, visible, title, evergreen, title_place,
                            image_alt_place, tourism_place) if c is not None]
    if len({_normal(c) for c in evidence}) > 1:
        return None
    city = (structured or visible or title or evergreen or title_place
            or image_alt_place or tourism_place)
    if not city or (row.get("city") and _normal(city) != _normal(row["city"])):
        return None
    return {"slug": row["slug"], "city": city, "source": row["officialSite"]}


def official_city_links(home_html, homepage, edition_year=None):
    """Select only same-host current-edition news + access pages.

    Link text is NOT trusted as evidence, merely a bounded discovery hint.
    """
    if (safe_public_url(homepage) is None or not isinstance(home_html, str)
            or not 0 < len(home_html) <= 650_000
            or (edition_year is not None
                and (type(edition_year) is not int
                     or not 2026 <= edition_year <= 2049))):
        return []
    parser = _VisibleOrganizerLinks()
    try:
        parser.feed(home_html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return []
    host = urlsplit(homepage).hostname
    selected = {}
    for href, label in parser.links[:250]:
        if not isinstance(href, str) or not 1 <= len(href) <= 900:
            continue
        try:
            candidate = urljoin(homepage, href)
            parts = urlsplit(candidate)
            decoded = unquote(parts.path)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if (parts.hostname != host or parts.query
                    or not decoded.startswith("/")
                    or any(p in (".", "..") for p in decoded.split("/"))
                    or re.search(r"%(?:2f|5c|2e|00)", parts.path, re.I)
                    or safe_public_url(url) is None or url == homepage):
                continue
            target = decoded.replace("-", " ").replace("_", " ")
            text = f"{target} {label}"
            if (EXCLUDE.search(target) or not CURRENT.search(text)
                    or (edition_year is not None
                        and str(edition_year) not in text)):
                continue
            selected[url] = 0 if re.search(r"\b20[2-4]\d\b", text) else 1
        except (ValueError, TypeError, UnicodeError):
            continue
    if edition_year is None:
        for i, url in enumerate(official_access_links(home_html, homepage)):
            selected.setdefault(url, 3 + i)
    ranked = sorted(selected, key=lambda url: (selected[url], len(url), url))
    chosen = ranked[:MAX_INTERNAL_PAGES]
    if edition_year is None and chosen:
        # Several 2027 marketing links can use BOTH bounded slots before
        # visiting the official NEWS INDEX with the exact dated article.
        # Reserve one of the SAME two slots for an already-validated,
        # SAME-HOST news index. No candidate/private URL may choose a host.
        news = next(
            (u for u in ranked if re.search(
                r"(?:/|^)(?:actu|news|actualite|nouveaute|articles)[a-z-]*(?:/|$)",
                unquote(urlsplit(u).path).casefold())),
            None)
        if news is not None and news not in chosen:
            chosen[-1] = news
    return chosen


def exact_city_from_official_site(row, fetcher=fetch_public_html):
    """Bounded current-edition proof across same-host home, index, and news.

    At most 1 homepage + 2 first-level pages + 2 edition-year news items.
    Every network URL is discovered again from fetched first-party HTML,
    checked with safe_public_url, DNS-pinned TLS and same-host restrictions.
    All *claims* must identify the current event and agree on one commune.
    """
    home = row.get("officialSite")
    if safe_public_url(home) is None:
        return None
    start = iso_day(row.get("startDate"))
    target_year = start.year if start is not None else undated_future_year(row)
    if target_year is None:
        return None
    body = fetcher(home)
    facts = []
    claim = exact_edition_city(body, row)
    if claim is not None:
        facts.append(claim)
    visited = {home}
    news_indexes = []
    for url in official_city_links(body, home):
        if url in visited:
            continue
        visited.add(url)
        try:
            page = fetcher(url)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            continue
        claim = exact_edition_city(page, row)
        if claim is not None:
            facts.append(claim)
        path = unquote(urlsplit(url).path).casefold()
        if re.search(r"(?:actu|news|nouveaute|articles)", path):
            news_indexes.append((url, page))
    further = []
    for index_url, index_page in news_indexes:
        for linked in official_city_links(index_page, index_url, edition_year=target_year):
            if linked not in visited and linked not in further:
                further.append(linked)
            if len(further) >= MAX_NESTED_NEWS_PAGES:
                break
        if len(further) >= MAX_NESTED_NEWS_PAGES:
            break
    for url in further:
        visited.add(url)
        try:
            claim = exact_edition_city(fetcher(url), row)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            continue
        if claim is not None:
            facts.append(claim)
    if not facts or any(
            _normal(x["city"]) != _normal(facts[0]["city"]) for x in facts):
        return None
    labels = {_normal(x["departmentLabel"]) for x in facts
              if x.get("departmentLabel")}
    if len(labels) > 1:
        return None
    result = dict(facts[0])
    if labels:
        result["departmentLabel"] = next(
            x["departmentLabel"] for x in facts if x.get("departmentLabel"))
    return result


def review(state, calendar, today, fetcher=fetch_public_html, limit=MAX_CHECKS):
    day = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid private city observer input")
    observations = state.setdefault(STATE_KEY, {})
    cursor = state.get(CURSOR_KEY, 0)
    if (not isinstance(observations, dict) or len(observations) > 150
            or type(cursor) is not int or not 0 <= cursor <= 1_000_000):
        raise ValueError("Invalid city observer state")
    dated = eligible(calendar, today)
    undated = eligible_undated(calendar, today)
    rows = [r for r in dated + undated
            if safe_public_url(r.get("officialSite")) and r.get("showOnMap") is not True
            and r.get("futureVenueConfirmed") is not True]
    active = {r["slug"] for r in rows}
    for slug in list(observations):
        if slug not in active:
            del observations[slug]
    yesterday = (day - timedelta(days=1)).isoformat()
    pending = [r for r in rows if (
        isinstance(observations.get(r["slug"]), dict)
        and observations[r["slug"]].get("lastSeen") == yesterday
        and observations[r["slug"]].get("firstSeen") == yesterday)]
    rest = [r for r in rows if r not in pending]
    rotated = rest[cursor % len(rest):] + rest[:cursor % len(rest)] if rest else []
    selected = (pending + rotated)[:limit]
    state[CURSOR_KEY] = cursor + max(1, len(selected))
    findings = []
    for row in selected:
        slug = row["slug"]
        result = {"slug": slug, "status": "CITY_NOT_PROVEN"}
        try:
            claim = exact_city_from_official_site(row, fetcher)
        except (OSError, ValueError, TimeoutError, UnicodeError) as exc:
            claim = None
            result["status"] = "OFFICIAL_FETCH_UNAVAILABLE"
            result["fetch_failure_code"] = safe_fetch_failure_code(exc)
        if claim is None:
            # A network/TLS/HTTP outage is not contradictory evidence.
            # Keep a real previous observation intact, without advancing
            # lastSeen or marking this failed civil day as a second proof.
            if result["status"] != "OFFICIAL_FETCH_UNAVAILABLE":
                observations.pop(slug, None)
            findings.append(result)
            continue
        digest = sha256(json.dumps(
            {"city": _normal(claim["city"]), "source": claim["source"],
             "department": _normal(claim.get("departmentLabel", ""))},
            sort_keys=True).encode("utf-8")).hexdigest()
        previous = observations.get(slug)
        stable = (isinstance(previous, dict) and previous.get("digest") == digest
                  and ((previous.get("lastSeen") == yesterday
                        and (previous.get("firstSeen") == yesterday
                             or previous.get("stable") is True))
                       or (previous.get("lastSeen") == today
                           and previous.get("stable") is True)))
        first = previous["firstSeen"] if stable else today
        observations[slug] = {"digest": digest, "firstSeen": first,
                              "lastSeen": today, "stable": stable}
        result.update(status=("TWO_DAY_STABLE_REVIEW_ONLY" if stable
                              else "FIRST_DAY_REVIEW_ONLY"),
                      candidate_city=claim, first_seen=first,
                      publication_authorized=False)
        findings.append(result)
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "publisher_city_sync_connected": False,
        "eligible": len(rows), "checked": len(selected),
        "first_day": sum(r["status"] == "FIRST_DAY_REVIEW_ONLY" for r in findings),
        "two_day_stable": sum(
            r["status"] == "TWO_DAY_STABLE_REVIEW_ONLY" for r in findings),
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_file = args.intake / "source-watch-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    catalogue = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = review(state, catalogue, today, limit=args.limit)
    _atomic(state_file, state)
    _atomic(args.intake / "future-festival-city-review.json", report)
    print("Private exact-edition city research; no map pin or public write")


if __name__ == "__main__":
    main()
