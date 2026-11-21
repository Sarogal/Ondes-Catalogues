"""Independent first-party verifier for venue pages with paragraph bills.

A whole venue is approved once through generic_first_party_venue_specs_v1,
NEVER a list of allowed artists or individual concerts. A fresh page must
contain one single event heading followed immediately by its full date and
one standalone (ARTIST GENRE / COUNTRY) paragraph for EACH named performer.
No biographical text or general venue style can supply a genre.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import generic_music_event as generic
import triage
import official_rss_jsonld_bridge as bridge

SOURCE = "agenda_officiel_astrolabe_detail_review"
PROFILE = "paragraph-artist-genre-v1"
# This venue-specific first-party source is independently pinned in the
# immutable generic venue specs. More venues can share this format.
VENUE_ID = "l-astrolabe-orleans"
DATE_LINE = re.compile(
    r"^\s*([0-3]\d)\.([01]\d)\.(20\d{2})\s+-\s+"
    r"\d{1,2}H[0-5]\d\s+-\s+(.{2,90})\s*$", re.I)
ARTIST_STYLE = re.compile(r"^\s*(.{2,120}?)\s*\(\s*(.{2,120}?)\s*\)\s*$")
CANCEL = re.compile(r"\b(?:annule|annulee|reporte|reportee|cancelled|postponed)\b")
# These are named halls from the first-party venue itself, NOT a list of
# artists. They prevent an unrelated page at the same host claiming a site.
HALLS = frozenset({"le club", "grande salle"})


class _MainParagraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_count = 0
        self.in_main = False
        self.paragraph = None
        self.blocks = []
        # Official headers can be plain div text while performer styles live
        # in paragraphs. Only text inside the unique <main> is inspected.
        self.main_text_nodes = []
        self.skip_tag = None

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.main_count += 1
            self.in_main = True
        elif self.in_main and tag in {"script", "style", "nav", "aside"}:
            self.skip_tag = tag
        elif self.in_main and not self.skip_tag and tag == "p":
            if self.paragraph is not None:
                raise ValueError("nested official paragraphs")
            self.paragraph = []

    def handle_data(self, text):
        if self.in_main and not self.skip_tag:
            if text.strip():
                self.main_text_nodes.append(text)
            if self.paragraph is not None:
                self.paragraph.append(text)

    def handle_endtag(self, tag):
        if tag == self.skip_tag:
            self.skip_tag = None
        elif tag == "p" and self.in_main and self.paragraph is not None:
            joined = " ".join(" ".join(self.paragraph).split())
            if joined:
                self.blocks.append(joined)
            self.paragraph = None
        elif tag == "main":
            if self.paragraph is not None:
                raise ValueError("unclosed official paragraph")
            self.in_main = False


# The event date/hall is still a unique, full, first-party witness.
# Some official venues render their title/date/category as div elements and
# reserve <p> for individual BAND (GENRE / COUNTRY) credits.
DIV_DATE = re.compile(
    r"(?<!\d)([0-3]\d)\.([01]\d)\.(20\d{2})\s*[-–—]\s*"
    r"\d{1,2}H[0-5]\d\s*[-–—]\s*(LE CLUB|GRANDE SALLE)\b", re.I)


def _div_event_header(text_nodes, expected_title, today):
    if not isinstance(expected_title, str) or not 3 <= len(expected_title) <= 800:
        raise ValueError("Ambiguous official dated concert headline")
    page = " ".join(" ".join(node.split()) for node in text_nodes)
    if not 100 <= len(page) <= 250_000:
        raise ValueError("Ambiguous official dated concert headline")
    title_pattern = (r"(?<!\w)" +
                     r"\s+".join(re.escape(word) for word in expected_title.split())
                     + r"(?!\w)")
    titles = list(re.finditer(title_pattern, page, re.I))
    dates = list(DIV_DATE.finditer(page))
    witnesses = []
    for title in titles:
        for date in dates:
            if not 0 <= date.start() - title.end() <= 180:
                continue
            try:
                when = dt.date(int(date[3]), int(date[2]), int(date[1]))
            except ValueError:
                continue
            if when < today or triage.words(date[4]) not in HALLS:
                continue
            # Visible category, heading and exact dated hall must form one
            # compact first-party header; a biography/tour list cannot stand in.
            preceding = page[max(0, title.start() - 180):title.start()].strip()
            if not preceding:
                continue
            witnesses.append((expected_title, when.isoformat(),
                              page[max(0, title.start() - 180):min(len(page), date.end() + 400)]))
    # Repeated/mismatching headlines are ambiguous, not a permission to pick.
    if len(witnesses) != 1:
        raise ValueError("Ambiguous official dated concert headline")
    return witnesses[0]


def _read_bill(html, today, expected_title=None):
    if not isinstance(html, str) or not 100 <= len(html) <= 1_000_000:
        raise ValueError("Official first-party event page invalid")
    parser = _MainParagraphs()
    parser.feed(html)
    parser.close()
    paragraphs = parser.blocks
    if parser.main_count != 1 or len(paragraphs) < 5:
        raise ValueError("No single official event body")

    # One event title must be located BETWEEN a dedicated genre/category
    # paragraph and an exact event date/venue paragraph, near the start.
    headers = []
    for n in range(1, min(12, len(paragraphs) - 1)):
        preceding, title, line = paragraphs[n - 1:n + 2]
        match = DATE_LINE.fullmatch(line)
        if not match or not 3 <= len(title) <= 800:
            continue
        try:
            day = dt.date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            continue
        if day < today or triage.words(match[4]) not in HALLS:
            continue
        # Explicit first-party event genre is useful context but performers
        # still carry individual genres. An unrelated hall menu is not proof.
        if not preceding or len(preceding) > 200:
            continue
        headers.append((n, title, day.isoformat()))
    if len(headers) == 1:
        index, title, when = headers[0]
        artist_paragraphs = paragraphs[index + 2:index + 120]
        status_context = " ".join(paragraphs[max(0, index - 1):index + 4])
    elif not headers:
        # No paragraph header: verify the unique title/date/hall rendered in
        # the main element's ordinary div text, never in a site menu or footer.
        title, when, status_context = _div_event_header(
            parser.main_text_nodes, expected_title, today)
        artist_paragraphs = paragraphs[:120]
    else:
        raise ValueError("Ambiguous official dated concert headline")
    if CANCEL.search(triage.words(status_context)):
        raise ValueError("Cancelled or postponed concert")

    pieces = [part.strip() for part in re.split(r"\s+\+\s+", title)]
    guest = None
    if pieces and triage.words(pieces[-1]) in {
            triage.words(n) for n in bridge._UNANNOUNCED}:
        guest = pieces.pop()
    if not pieces or any(not 2 <= len(x) <= 120 for x in pieces):
        raise ValueError("Ambiguous concert lineup")
    if len({triage.words(x) for x in pieces}) != len(pieces):
        raise ValueError("Duplicate group names on first-party bill")

    # Only short, standalone BAND (EXPLICIT GENRE / COUNTRY) lines count.
    # In particular, a genre keyword in a descriptive biography cannot
    # identify a new performer or make a non-metal headliner eligible.
    found = []
    for block in artist_paragraphs:
        m = ARTIST_STYLE.fullmatch(block)
        if m is None:
            continue
        artist, style = m.groups()
        if triage.words(artist) not in {triage.words(x) for x in pieces}:
            # Ignore ticketing/organization parentheses, but never invent
            # an unexpected group in the title.
            continue
        genre = style.split("/", 1)[0].strip(" –—-\t")
        if not 2 <= len(genre) <= 80:
            raise ValueError("Invalid individually labelled performer style")
        found.append((artist.strip(), genre))
    if len(found) != len(pieces) or any(
            triage.words(found[i][0]) != triage.words(pieces[i])
            for i in range(len(pieces))):
        raise ValueError("One official artist-genre paragraph per musician required")
    genres, seen = [], set()
    for _, genre in found:
        key = triage.words(genre)
        if key not in seen:
            seen.add(key)
            genres.append(genre)
    if not generic.independently_relevant_genre(genres):
        raise ValueError("No relevant genre on any named artist")
    return {"title":title, "date":when, "artists":pieces,
            "genres":genres, "unnamed":guest}


def verify(candidate, html_text, catalogue, today):
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or not isinstance(candidate, dict)
            or candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Untrusted first-party paragraph lead")
    match = generic.trusted_spec(candidate)
    if match is None or match[0] != VENUE_ID:
        raise ValueError("Untrusted venue source or HTTPS event path")
    venue_id, spec = match
    origin = candidate.get("sourcePage")
    if origin is not None:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or parsed.hostname != spec["host"]
                or parsed.port or parsed.username or parsed.password):
            raise ValueError("Untrusted discovery source authority")
    if not isinstance(catalogue, dict):
        raise ValueError("Missing public venue catalogue")
    venues = [v for v in catalogue.get("venues", [])
              if isinstance(v, dict) and v.get("id") == venue_id]
    if len(venues) != 1 or (
            generic.norm(venues[0].get("name")) != generic.norm(spec["name"])
            or generic.norm(venues[0].get("city")) != generic.norm(spec["city"])
            or str(venues[0].get("department")) != spec["department"]):
        raise ValueError("Official first-party venue identity changed")
    exact = _read_bill(html_text, today, candidate.get("name"))
    if (exact["date"] != candidate.get("date")
            or generic.norm(exact["title"]) != generic.norm(candidate.get("name"))
            or generic.norm(exact["artists"][0]) != generic.norm(
                candidate.get("leadArtist"))):
        raise ValueError("First-party event date, headline or artist changed")
    event = generic.approve_verified_bill(
        catalogue, venue_id, spec, candidate["sourceUrl"], today,
        exact["date"], exact["artists"], exact["genres"],
        exact["unnamed"], "verified-first-party-visible-bill-v1")
    event["officialEvidence"][0]["visibleBillProfile"] = PROFILE
    return event
