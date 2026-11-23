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
    MAX_CHECKS, _VisibleOrganizerLinks, _matching_event, _name, _country,
    _atomic, eligible, official_access_links,
)
SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_structured_roster import (
    JsonLD, SENSITIVE_STATUSES, edition_name, iso_day, walk,
)
from grossesondes_official_html_edition import (
    CANCEL, VisibleParagraphs, dominant_visible_range, explicit_ranges, fold,
)

SCHEMA = "grossesondes.future-festival-city-private.v1"
STATE_KEY = "future_edition_city_observations_private"
CURSOR_KEY = "future_edition_city_rotation_cursor"
MAX_INTERNAL_PAGES = 2
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
    branded = any(name.search(" ".join(fold(raw).split())) for raw in blocks)
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
    """Maintain visible same-section boundaries without joining old editions."""
    SECTION = "\x1e"

    def handle_starttag(self, tag, attrs):
        if tag == "section" and not self.hidden():
            self.parts.append(self.SECTION)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "section" and not self.hidden():
            self.parts.append(self.SECTION)
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
    if not name.search(" ".join(fold(" ".join(parser.parts)).split())):
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
        folded = " ".join(fold(" ".join(parts)).split())
        years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", folded))
        if (years != {str(year)} or CANCEL.search(folded)
                or any(explicit_ranges(folded, year))):
            continue
        for i in range(len(parts) - 3):
            if not heading.search(" ".join(fold(parts[i]).split())):
                continue
            genre, raw_city, raw_dept = parts[i + 1:i + 4]
            if not re.search(r"\bfestival\b", fold(genre)):
                continue
            if not locality.fullmatch(raw_city) or not locality.fullmatch(raw_dept):
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
    evidence = [c for c in (structured, visible, title) if c is not None]
    if len({_normal(c) for c in evidence}) > 1:
        return None
    city = structured or visible or title
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
        except (OSError, ValueError, TimeoutError, UnicodeError):
            claim = None
            result["status"] = "OFFICIAL_FETCH_UNAVAILABLE"
        if claim is None:
            observations.pop(slug, None)
            findings.append(result)
            continue
        digest = sha256(json.dumps(
            {"city": _normal(claim["city"]), "source": claim["source"]},
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
