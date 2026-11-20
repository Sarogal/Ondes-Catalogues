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
        if self.in_main and not self.skip_tag and self.paragraph is not None:
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


def _read_bill(html, today):
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
    if len(headers) != 1:
        raise ValueError("Ambiguous official dated concert headline")
    index, title, when = headers[0]
    if CANCEL.search(triage.words(" ".join(paragraphs[max(0,index-1):index+4]))):
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
    for block in paragraphs[index + 2:index + 120]:
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
    exact = _read_bill(html_text, today)
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
