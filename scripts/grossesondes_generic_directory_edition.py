"""Publisher proof for previously unknown festivals linked by a public directory.

A directory entry proves only an attributed first-party website link, never
2027 dates, venue or a festival publication. The publisher reconstructs the
directory URL from the edition NAME (not an untrusted private URL), independently
fetches the page, extracts one visible attributed official website and then
independently checks the precise future edition on that site's DNS-pinned HTTPS.
No named-festival allowlist; malformed, ambiguous and conflicting claims fail
closed. The public addition contains no inferred artists, venue or map pin.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url
from source_qualification import Anchors, normalized, visible_text
from grossesondes_institutional_linked_edition import prove_dates
from grossesondes_official_html_edition import (
    VisibleParagraphs, explicit_ranges, dominant_visible_range,
    administrative_calendar_dates, visible_official_edition, fold, CANCEL,
)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction
from festival_event_kind import touring_concert_stop
from grossesondes_institutional_edition import (
    slug_for, conflicts_with_signed_catalogue,
)
from grossesondes_structured_edition import ROW_KEYS, PRIVATE_KEYS

PROOF_MODE = "generic-directory-first-party-edition.v1"
DIRECTORY = "https://www.festivalenfrance.com/festival/"
PRIVATE_NOTES = (
    "Site officiel lié par un annuaire indépendant ; dates actuelles "
    "et genre à revérifier par le publisher. Lieu, artistes et coordonnées inconnus."
)
PUBLISHED_NOTES = (
    "Lien vers le site du festival retrouvé dans un annuaire public puis "
    "dates et genre revérifiés directement sur le site officiel. "
    "Lieu exact, artistes et coordonnées à confirmer."
)
PRIVATE_STATUS = "Provenance et édition en attente de recontrôle indépendant"
PUBLISHED_STATUS = "Provenance et édition revérifiées indépendamment"
PRIVATE_CONFIDENCE = "Annuaire public (site lié) + preuve primaire en attente"
PUBLISHED_CONFIDENCE = "Annuaire public (lien vérifié) + site officiel (dates)"
GENRE = re.compile(r"\b(?:metal|hard rock|punk|rock|hardcore|stoner|doom|"
                   r"sludge|grindcore|deathcore|metalcore|black metal|"
                   r"thrash metal|heavy metal)\b")
CANCELLED = re.compile(
    r"\b(?:edition|festival)\s+20[2-4][0-9]\s+"
    r"(?:annulee?|reporte[e]?|cancelled|postponed)\b"
)


class Heading(HTMLParser):
    """Visible h1 text only, with concealed ancestors ignored."""
    HIDDEN_TAGS = {"script", "style", "template", "noscript", "svg"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img",
            "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.current = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = (attributes.get("style") or "").replace(" ", "").lower()
        parent_hidden = bool(self.stack and self.stack[-1][1])
        hidden = (parent_hidden or tag in self.HIDDEN_TAGS
                  or "hidden" in attributes
                  or attributes.get("aria-hidden") == "true"
                  or "display:none" in style)
        if tag not in self.VOID:
            self.stack.append((tag, hidden))
        if tag == "h1" and not hidden:
            self.current = []

    def handle_data(self, value):
        if (self.current is not None and
                self.stack and not self.stack[-1][1]):
            self.current.append(value)

    def handle_endtag(self, tag):
        if tag == "h1" and self.current is not None:
            self.headings.append(normalized(" ".join(self.current)))
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

def directory_urls(title):
    """Only bounded title-derived paths on ONE independently fetched directory.

    The directory uses both compact paths (festibarockin) and hyphenated
    paths (mozhell-open-air). A missed slug is a discovery failure, not
    grounds to fetch a private queue URL or skip an unknown festival.
    """
    if not isinstance(title, str) or not 8 <= len(title) <= 150:
        return ()
    m = re.fullmatch(r"(.{7,130}?)\s+(20[2-4][0-9])", title.strip())
    if m is None:
        return ()
    words = normalized(m.group(1)).split()
    compact = "".join(words)
    dashed = "-".join(words)
    if not re.fullmatch(r"[a-z][a-z0-9]{7,75}", compact):
        return ()
    paths = [DIRECTORY + compact]
    if (dashed != compact
            and len(dashed) <= 100
            and re.fullmatch(r"[a-z][a-z0-9-]{7,99}", dashed)):
        paths.append(DIRECTORY + dashed)
    return tuple(paths)


def directory_url(title):
    """Back-compatible primary directory path; no private URL is trusted."""
    variants = directory_urls(title)
    return variants[0] if variants else None


def trusted_linked_site(directory_html, title):
    """Exact visible h1 and an unambiguous labelled external website."""
    if (directory_url(title) is None or not isinstance(directory_html, str)
            or not 0 < len(directory_html) <= 650_000):
        return None
    header = Heading()
    anchors = Anchors()
    try:
        header.feed(directory_html)
        header.close()
        anchors.feed(directory_html)
        anchors.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    base = normalized(title.rsplit(" ", 1)[0])
    if header.headings.count(base) != 1:
        return None
    urls = set()
    for href, label, prefix in anchors.anchors[:700]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        if safe_public_url(href) is None:
            continue
        parts = urlsplit(href)
        if parts.scheme != "https" or parts.username or parts.password or (
                parts.path not in ("", "/") or parts.query or parts.fragment):
            continue
        host = parts.hostname or ""
        if host in ("www.festivalenfrance.com", "festivalenfrance.com"):
            continue
        # Link text must name the destination or its exact editorial role.
        link = normalized(label)
        context = normalized(prefix)
        hostname = normalized(host.removeprefix("www."))
        # The real directory also uses a local "Web: www.example.fr"
        # contact line. A generic ticket, social or sponsor URL is NOT an
        # official website merely because its host is mentioned on the page.
        role = ("site web" in context or "site officiel" in context
                or context == "web" or context.endswith(" web")
                or link in ("site web", "site officiel"))
        # A labelled link to a different host is a conflict even when a
        # preceding list item labels it "site web".
        if not (role and
                link in (hostname, normalized(host), "site web", "site officiel")):
            continue
        if not re.search(r"\b(?:site web|site officiel|web)\b", context + " " + link):
            continue
        canonical = "https://" + host + "/"
        if safe_public_url(canonical) is None:
            continue
        urls.add(canonical)
    return next(iter(urls)) if len(urls) == 1 else None


def discover_directory_website(title, directory_fetch):
    """Read at most two deterministic directory URLs; return only a lead.

    A private candidate's URL or host never influences the network request.
    A 404/failed compact alias must not prevent the next safe title variant.
    This alone conveys no festival publication authority.
    """
    for url in directory_urls(title):
        try:
            html = directory_fetch(url)
            site = trusted_linked_site(html, title)
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            continue
        if site is not None:
            return url, site
    return None, None


def visible_adjacent_edition_dates(html, title, year, today):
    """Exact name + immediately adjacent visible date block, never metadata.

    Some first-party hero sections split the festival heading and its dates
    into adjacent elements instead of a single paragraph. No text from
    private queues, hidden markup, footers, generic year labels or unrelated
    festival listings can grant authority. Only a first-party page already
    independently linked from the public directory reaches this function.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 650_000
            or not isinstance(title, str) or type(year) is not int
            or not 2026 <= year <= 2049):
        return None
    name = normalized(title.rsplit(" ", 1)[0])
    if not 8 <= len(name) <= 130:
        return None
    try:
        checked = date.fromisoformat(today)
        parser = VisibleParagraphs()
        parser.feed(html)
        parser.close()
        chunks = [text for chunk in
                  " ".join(parser.parts).split(VisibleParagraphs.SEP)
                  if (text := " ".join(fold(chunk).split()))]
        pairs = []
        for index, chunk in enumerate(chunks[:-1]):
            if normalized(chunk) != name:
                continue
            next_chunk = chunks[index + 1]
            if (not 8 <= len(next_chunk) <= 140
                    or CANCEL.search(next_chunk)
                    or re.search(r"\b(?:billetterie|tickets?|vente|prevente|"
                                 r"ouverture|inscription|sold out)\b", next_chunk)):
                continue
            years = {int(y) for y in re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])",
                                                 next_chunk)}
            if years != {year}:
                continue
            found = list(explicit_ranges(next_chunk, year))
            if len(found) != 1:
                continue
            a, b, start, end = found[0]
            # The adjacent block must BE the printed event date, not
            # an unrelated descriptive paragraph which happens to contain it.
            surrounding = (next_chunk[:a] + next_chunk[b:]).strip(" :;.,- ")
            if surrounding not in ("", "dates", "date", "dates du festival"):
                continue
            if start < checked or start.year != year or end.year != year:
                continue
            pairs.append((start, end))
        if not pairs or len(set(pairs)) != 1:
            return None
        start, end = pairs[0]
        # Other printed current-year event ranges can veto this near-title
        # hero. Ticket on-sale dates in isolated paragraphs are excluded
        # only by the already tested administrative-calendar rule.
        body = " ".join(fold(" ".join(parser.parts)).split())
        excludes = administrative_calendar_dates(html, title, year)
        all_dates = {(a, b) for _s, _e, a, b
                     in explicit_ranges(body, year)
                     if (a, b) not in excludes}
        # The normal first-party date verifier explicitly vetoes touring
        # formats even when they contain a marketing "Fest" name. Its new
        # adjacent-block fallback must enforce the SAME tour classification.
        tour_claim = re.search(
            r"\b(?:tournee itinerante|tournee de [0-9]+ concerts?|"
            r"concerts? de la tournee|date de la tournee|concert tour|"
            r"tour de concerts?)\b", body)
        if (dominant_visible_range(all_dates) != (start, end)
                or tour_claim
                or touring_concert_stop(html, start, end)
                or not no_same_edition_jsonld_contradiction(
                    html, title, start, end)):
            return None
        return start.isoformat(), end.isoformat()
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
        return None


def _misleading_adjacent_date(html, title, year):
    """Never turn sale dates or a DIFFERENT following festival into this show.

    The legacy paragraph-proximity proof can see a valid date after the exact
    festival heading even when the next block explicitly says it belongs to
    a ticket on-sale or to a different festival. This negative filter applies
    before both the legacy proof and the new adjacent-date path.
    """
    try:
        parser = VisibleParagraphs()
        parser.feed(html)
        parser.close()
        chunks = [text for chunk in
                  " ".join(parser.parts).split(VisibleParagraphs.SEP)
                  if (text := " ".join(fold(chunk).split()))]
        name = normalized(title.rsplit(" ", 1)[0])
        for index, chunk in enumerate(chunks[:-1]):
            if normalized(chunk) != name:
                continue
            near = chunks[index + 1]
            if (re.search(r"\b(?:ouverture|billetterie|tickets?|prevente|"
                          r"mise en vente|inscription)\b", near)
                    and any(explicit_ranges(near, year))):
                return True
            if (re.search(r"\b(?:autre|different|other|another)\b", near)
                    and re.search(r"\bfestival\b", near)
                    and index + 2 < len(chunks)
                    and any(explicit_ranges(chunks[index + 2], year))):
                return True
        return False
    except (TypeError, ValueError, UnicodeError):
        return True



def unique_current_edition_visible_dates(html, title, year, today):
    """Recover the event weekend without mistaking sale or programme days for it.

    This is an event-proof fallback, not an identity/host authorization:
    - ignore *only* independently labelled administrative ticket-sale dates;
    - tolerate single programme days wholly inside one announced weekend;
    - reject all other contradictory dates, missing event-name proximity,
      cancellations, unsupported structured data and explicit concert tours.
    A publisher still re-fetches an independently attributed organizer site.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 650_000
            or not isinstance(title, str) or type(year) is not int
            or not 2026 <= year <= 2049):
        return None
    try:
        checked = date.fromisoformat(today)
        parser = VisibleParagraphs()
        parser.feed(html)
        parser.close()
        visible = " ".join(fold(" ".join(parser.parts)).split())
        excluded = administrative_calendar_dates(html, title, year)
        intervals = {(start, end) for _a, _b, start, end
                     in explicit_ranges(visible, year)
                     if (start, end) not in excluded}
        chosen = dominant_visible_range(intervals)
        if chosen is None:
            return None
        start, end = chosen
        # Multi-day marketing tours are not standalone festival editions.
        # The older adjacent-heading proof already applies this exact veto;
        # the new paragraph fallback must not bypass it.
        explicit_tour = re.search(
            r"\b(?:tournee itinerante|tournee de [0-9]+ concerts?|"
            r"concerts? de la tournee|date de la tournee|"
            r"concert tour|tour de concerts?)\b", visible)
        if (explicit_tour or start < checked or start.year != year
                or end.year != year
                or not visible_official_edition(html, title, start, end)
                or not no_same_edition_jsonld_contradiction(
                    html, title, start, end)
                or touring_concert_stop(html, start, end)):
            return None
        return start.isoformat(), end.isoformat()
    except (TypeError, ValueError, UnicodeError, OverflowError):
        return None

def verify_primary(html, title, year, today):
    if not isinstance(html, str) or _misleading_adjacent_date(html, title, year):
        return None
    dates = prove_dates(html, title, year, today)
    if dates is None:
        dates = unique_current_edition_visible_dates(html, title, year, today)
    if dates is None:
        dates = visible_adjacent_edition_dates(html, title, year, today)
    if dates is None:
        return None
    try:
        words = visible_text(html)
    except (TypeError, ValueError, UnicodeError):
        return None
    if (not GENRE.search(words) or "festival" not in words
            or CANCELLED.search(words)):
        return None
    return dates



# Publication-side reconstruction: this is independent of private national
# article discovery, not an import of the private observation as authority.
# The site root is first derived from a newly fetched PUBLIC directory page.
MAX_PUBLISHER_SAME_HOST_PAGES = 3


def _publisher_same_host_links(html, site, year, today, *, second_level=False):
    """Find visible current-edition links from a verified first-party page.

    Only exact-host HTTPS, non-encoded paths without queries are allowed.
    Search terms rank generic page *roles*, never festival names or domains.
    Weekly rotation eventually covers a long menu while keeping J/J+1 stable.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 650_000
            or safe_public_url(site) != site or urlsplit(site).path != "/"
            or type(year) is not int):
        return []
    parser = Anchors()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return []
    host = urlsplit(site).hostname
    ranked = {}
    for href, label, _context in parser.anchors[:250]:
        if (not isinstance(href, str) or not 0 < len(href) <= 900
                or "%" in href or "\\" in href
                or any(part in (".", "..") for part in
                       urlsplit(href).path.split("/"))):
            continue
        try:
            candidate = urljoin(site, href)
            parts = urlsplit(candidate)
            if (parts.scheme != "https" or parts.hostname != host
                    or parts.port is not None or parts.username is not None
                    or parts.password is not None or parts.query or parts.fragment
                    or parts.path in ("", "/")
                    or safe_public_url(candidate) != candidate):
                continue
            descriptor = normalized(str(label) + " " +
                                    parts.path.replace("-", " ").replace("_", " "))
            years = set(re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])",
                                   descriptor))
            if years and years != {str(year)}:
                continue
            current_year = str(year) in years
            generic_role = bool(re.search(
                r"\b(?:programmation|programme|actualites?|actus?|news|"
                r"edition|editions|dates?|agenda|affiche|annonce|annonces)\b",
                descriptor))
            if (second_level and not current_year) or not (
                    current_year or generic_role):
                continue
            rank = 0 if current_year else 1
            ranked[candidate] = min(rank, ranked.get(candidate, rank))
        except (TypeError, ValueError, UnicodeError):
            continue
    current = sorted(url for url, rank in ranked.items() if rank == 0)
    generic = sorted(url for url, rank in ranked.items() if rank == 1)
    # Keep two consecutive days on the same deterministic rotation. No fixed
    # inventory of target article paths is permitted.
    week = date.fromisoformat(today).toordinal() // 7
    def rotate(urls):
        if not urls:
            return urls
        offset = (week * 2) % len(urls)
        return urls[offset:] + urls[:offset]
    return (rotate(current)[:2] + rotate(generic)[:1])[:3]


def _nonadministrative_dates_visible(html, title, year):
    """Other visible dates prohibit cherry-picking a convenient article."""
    if not isinstance(html, str):
        return True
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return True
    visible = " ".join(fold(" ".join(parser.parts)).split())
    excluded = administrative_calendar_dates(html, title, year)
    return any((first, last) not in excluded
               for _start, _end, first, last in
               explicit_ranges(visible, year))


def verify_official_site_pages(site, homepage_html, title, year, today,
                               fetch=fetch_public_html):
    """Recheck a directory-attributed SITE independently of private URL hints.

    Try the root first, then at most 3 independently downloaded same-host
    links. A news index may lead to a dated article. A mismatched range or
    current-edition cancellation prevents selection. Nothing from a private
    dossier chooses the downloaded paths or overrides conflicting evidence.
    """
    if (safe_public_url(site) != site or urlsplit(site).path != "/"
            or type(year) is not int):
        return None
    dates = verify_primary(homepage_html, title, year, today)
    if dates is not None:
        return dates
    try:
        visible_home = visible_text(homepage_html)
        if (CANCELLED.search(visible_home) or
                _nonadministrative_dates_visible(homepage_html, title, year)):
            return None
        pending = _publisher_same_host_links(
            homepage_html, site, year, today)
        seen = {site}
        observed = set()
        remaining = MAX_PUBLISHER_SAME_HOST_PAGES
        while pending and remaining:
            link = pending.pop(0)
            if link in seen:
                continue
            seen.add(link)
            remaining -= 1
            try:
                page = fetch(link)
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                # Network failure never supplies proof.
                continue
            event_dates = verify_primary(page, title, year, today)
            if event_dates is not None:
                if (not no_same_edition_jsonld_contradiction(
                        homepage_html, title,
                        date.fromisoformat(event_dates[0]),
                        date.fromisoformat(event_dates[1]))):
                    return None
                observed.add(tuple(event_dates))
            else:
                # A year-dated article with conflicting visible dates and the
                # festival name must veto the result, not be skipped to find
                # another convenient article.
                if (_nonadministrative_dates_visible(page, title, year)
                        and normalized(title.rsplit(" ", 1)[0]) in
                        normalized(visible_text(page))):
                    return None
                # A generic programme/news index may reveal a year-dated
                # article one level below. Still use the shared total budget.
                if remaining and not re.search(
                        r"(?<![0-9])" + str(year) + r"(?![0-9])", link):
                    for discovered in _publisher_same_host_links(
                            page, site, year, today, second_level=True):
                        if discovered not in seen and discovered not in pending:
                            pending.append(discovered)
        return next(iter(observed)) if len(observed) == 1 else None
    except (TypeError, ValueError, UnicodeError):
        return None


def private_proposal(title, site, dates, today, *, directory_ref=None):
    routes = directory_urls(title)
    if (not routes or slug_for(title) is None
            or not isinstance(site, str) or safe_public_url(site) is None):
        return None
    origin = directory_ref if directory_ref is not None else routes[0]
    if origin not in routes:
        return None
    try:
        parts = urlsplit(site)
        if (parts.scheme != "https" or not parts.hostname
                or parts.username or parts.password or parts.port
                or parts.path != "/" or parts.query or parts.fragment
                or site != "https://" + parts.hostname + "/"):
            return None
    except (TypeError, ValueError):
        return None
    try:
        start, end = map(date.fromisoformat, dates)
        current = date.fromisoformat(today)
    except (TypeError, ValueError):
        return None
    year = int(title.rsplit(" ", 1)[-1])
    if (not current <= start <= end or start.year != year
            or end.year != year or (end - start).days > 7
            or safe_public_url(site) is None):
        return None
    return {
        "slug": slug_for(title), "name": title,
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False, "lineup": [], "bands": 0,
        "price": None, "status": "Annoncé",
        "officialSite": site, "source": site,
        "lastVerified": today, "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": PROOF_MODE, "originSlug": origin,
        "evidence": [origin, site], "verified_at": today,
    }


def validate_private_proposal(row, today):
    if not isinstance(row, dict) or set(row) != ROW_KEYS | PRIVATE_KEYS:
        return None
    try:
        observed = date.fromisoformat(row["verified_at"])
        if (observed > date.fromisoformat(today)
                or (date.fromisoformat(today) - observed).days > 7):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    if (not isinstance(row.get("evidence"), list)
            or len(row["evidence"]) != 2
            or row.get("originSlug") not in directory_urls(row.get("name"))
            or row["evidence"] != [row.get("originSlug"),
                                    row.get("officialSite")]):
        return None
    expected = private_proposal(
        row.get("name"), row.get("officialSite"),
        (row.get("startDate"), row.get("endDate")), row["verified_at"],
        directory_ref=row["originSlug"])
    return expected if expected == row else None


def validate_verified_row(proposal, verified, today):
    if validate_private_proposal(proposal, today) is None:
        return None
    expected = {key: proposal[key] for key in ROW_KEYS}
    expected.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=PUBLISHED_NOTES,
    )
    return expected if verified == expected else None


def independently_verify(proposal, today, directory_fetch=fetch_public_html,
                         organizer_fetch=fetch_public_html):
    """Never fetch proposed organizer URL until rederived from fixed directory."""
    if validate_private_proposal(proposal, today) is None:
        return None
    # URL is in the finite name-derived set checked by the strict private
    # proposal contract, never accepted merely because private JSON supplied it.
    url = proposal["originSlug"]
    try:
        document = directory_fetch(url)
        site = trusted_linked_site(document, proposal["name"])
        if site is None or site != proposal["officialSite"]:
            return None
        html = organizer_fetch(site)
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return None
    year = int(proposal["name"].rsplit(" ", 1)[-1])
    dates = verify_official_site_pages(
        site, html, proposal["name"], year, today, fetch=organizer_fetch)
    if dates != (proposal["startDate"], proposal["endDate"]):
        return None
    approved = {key: proposal[key] for key in ROW_KEYS}
    approved.update(
        verificationStatus=PUBLISHED_STATUS,
        sourceConfidence=PUBLISHED_CONFIDENCE,
        notes=PUBLISHED_NOTES,
    )
    return approved
