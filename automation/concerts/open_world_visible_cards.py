"""Generic, quarantined first-party concert cards visible in ordinary HTML.

Some official sites present a semantic *sequence* of visible elements:
complete date -> named artist bill -> explicitly labelled concert genre ->
visible venue attribution, without Event/MusicEvent JSON-LD. This parser
recognizes the INFORMATION RELATIONSHIP, not a site-specific CSS selector,
domain, artist or address. A site URL from the private registry is NOT proof
that the room owns that domain. Results are discovery hints only; Publisher
must independently re-fetch, authenticate and geolocate the event.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import official_html_evidence as visible
from triage import words

MAX_HTML = 1_000_000
DATE_SEPARATOR = re.compile(r"\s+[–—―]\s+")
CONCERT_GENRE = re.compile(r"(?i)^\s*(?:concert|live concert|concert live)\s*[–—―-]\s*(.+?)\s*$")
VENUE_ARROW = re.compile(r"^\s*[→➡]\s*(.+?)\s*$")
TRAILING_KIND = re.compile(r"\s+[–—―-]\s+(?:salle\b|music venue\b|concert hall\b).*", re.I)
CANCELLED = re.compile(
    r"\b(?:annule|annulee|report|reporte|reportee|cancelled|canceled|postponed|rescheduled)\b")
ARTIST_SPLIT = re.compile(r"\s+\+\s+")
PLACEHOLDER = frozenset({"tba", "guest", "special guest",
                         "premiere partie", "artiste surprise", "a confirmer"})


def _room_key(raw):
    key = words(raw)
    return re.sub(r"^(?:le|la|les|l|the)\s+", "", key)


def _date(text):
    # The standalone em dash joining day and month is decorative; the date
    # still MUST supply an explicit full year and a valid calendar day.
    normalized = DATE_SEPARATOR.sub(" ", text)
    found = visible._date_in(normalized)
    if not isinstance(found, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", found):
        return None
    return found


def _artists(label):
    label = " ".join(str(label or "").split())
    if not 2 <= len(label) <= MAX_HTML:
        return None
    names = [x.strip() for x in ARTIST_SPLIT.split(label)]
    if (not names
            or any(not 2 <= len(x) <= 120 for x in names)
            or any(words(x) in PLACEHOLDER for x in names)
            or len({words(x) for x in names}) != len(names)):
        return None
    if any(re.search(r"(?i)\b(?:billetterie|concert|ouverture|portes|salle)\b", x)
           for x in names):
        return None
    return names


def extract(html, room, city, today):
    """Return strictly associated event-card leads, never a publication claim.

    Use only <p>-level visible blocks. Recommendation panels often have
    <h2> date / <h5> genre / <h3> artist but are NOT official detail proof:
    do not join them with the primary venue page or nearby paragraphs.
    """
    if (not isinstance(html, str) or len(html) > MAX_HTML
            or not isinstance(room, str) or not 2 <= len(room) <= 140
            or not isinstance(city, str) or not 2 <= len(city) <= 120
            or not isinstance(today, dt.date) or isinstance(today, dt.datetime)):
        return []
    parser = visible.VisibleBlocks(complete_blocks=True)
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, RecursionError):
        return []
    blocks = parser.blocks
    # An official venue page must at least display the asserted city.
    # This is a weak correlation, not origin or geographic attestation.
    if not visible._contains(" ".join(x for _, x in blocks), city):
        return []
    paras = [x for tag, x in blocks if tag == "p"]
    matches, identities = [], set()
    for i in range(len(paras) - 3):
        date = _date(paras[i])
        if not date or date < today.isoformat():
            continue
        artists = _artists(paras[i + 1])
        if not artists:
            continue
        genre_match = CONCERT_GENRE.fullmatch(paras[i + 2])
        place_match = VENUE_ARROW.fullmatch(paras[i + 3])
        if not genre_match or not place_match:
            continue
        genre = visible._explicit_label(genre_match[1])
        name = TRAILING_KIND.sub("", place_match[1]).strip()
        if (not genre or _room_key(name) != _room_key(room)
                or not _room_key(name)):
            continue
        around = " ".join(paras[max(0, i - 2): i + 4])
        if CANCELLED.search(words(around)):
            continue
        key = (date, tuple(words(a) for a in artists), _room_key(name))
        if key in identities:
            continue
        identities.add(key)
        matches.append({
            "date": date, "artists": artists, "genre": genre,
            "venue": room, "city": city,
            "evidenceScope": "visible-event-card-review-only",
        })
    return matches


class _FooterAddress(HTMLParser):
    """Only a real footer's address text; never event, artist or genre evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_footer = False
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "footer":
            self.in_footer = True
        if self.in_footer and tag in {"script", "style", "noscript", "svg", "form"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag == "footer":
            self.in_footer = False
            self.ignored = 0
        elif self.in_footer and self.ignored and tag in {
                "script", "style", "noscript", "svg", "form"}:
            self.ignored -= 1

    def handle_data(self, text):
        if self.in_footer and not self.ignored:
            self.parts.append(text)


def _footer_location(html, city, address, postal):
    if not isinstance(address, str) or len(words(address)) < 5:
        return False
    if not isinstance(postal, str) or not re.fullmatch(r"\d{5}", postal):
        return False
    parser = _FooterAddress()
    parser.feed(html)
    parser.close()
    content = " ".join(parser.parts)
    return (visible._contains(content, address)
            and visible._contains(content, postal + " " + city))


def verified_detail(html, room, city, when, *, address=None, postal=None,
                    diagnostics=None):
    """Verify a single first-party HTML event after INDEPENDENT source ownership.

    Both artist-H1 pages and venue-branded H1 pages with an explicit
    presenter heading are common. Venue-branded PROGRAMME LISTINGS alone do
    not prove a concert: require one full date + named bill + compact event
    genre + matching venue card before any recommendation section. Never
    infer genres from descriptive paragraphs or from nearby events.
    """
    def held(reason):
        if diagnostics is not None:
            diagnostics["visibleDetail"] = reason
        return None

    try:
        day = dt.date.fromisoformat(when)
    except (TypeError, ValueError):
        return held("invalid_date")
    if not isinstance(html, str) or len(html) > MAX_HTML:
        return held("invalid_html")
    parsed = visible.VisibleBlocks(leaf_divs=True, complete_blocks=True)
    try:
        parsed.feed(html)
        parsed.close()
    except (ValueError, TypeError, RecursionError):
        return held("html_parse_error")
    blocks = parsed.blocks
    # Footer text is intentionally excluded from the musical parser. A
    # matching exact published address + postcode/city can nevertheless
    # corroborate the already independently authenticated physical venue.
    if not visible._contains(" ".join(t for _, t in blocks), city):
        if not _footer_location(html, city, address, postal):
            return held("city_or_exact_footer_address_missing")
    headings = [(i, t) for i, (tag, t) in enumerate(blocks) if tag == "h1"]
    if len(headings) != 1:
        return held("single_h1_missing")
    start, title = headings[0]
    if re.search(r"\b(?:festival|fest)\b", words(title)):
        return held("festival_heading")
    brand_heading = _room_key(title) == _room_key(room)
    names = None if brand_heading else _artists(title)
    if not brand_heading and not names:
        return held("invalid_artist_heading")
    section = blocks[start + 1:]
    # Recommendations may be introduced by ordinary paragraphs, not just
    # semantic H2/H3 headings. Their cards cannot attest this primary event.
    end_labels = visible.END_SECTION | {
        "vous devriez aimer", "recommandations", "related concerts"
    }
    cutoff = next((i for i, (tag, t) in enumerate(section)
                   if tag in {"p", "h2", "h3", "h4", "h5", "div", "span", "strong", "text"}
                   and words(t) in end_labels), len(section))
    section = section[:min(cutoff, 160)]
    if CANCELLED.search(words(" ".join(t for _, t in section))):
        return held("cancellation_word_in_section")
    if brand_heading:
        # A venue's calendar list is NOT an individual event detail. Only a
        # presenter's dedicated show page can supply this second HTML shape.
        first_date_idx = next((i for i, (tag, t) in enumerate(section)
                               if tag in {"p", "time", "strong", "text", "div", "span", "h2", "h3", "h4", "h5"}
                               and _date(t)), len(section))
        preceding = section[:first_date_idx]
        if not any(tag in {"h2", "h3"}
                   and re.search(r"\b(?:presente|presentent|presents|presented by)\b",
                                 words(t))
                   for tag, t in preceding):
            return held("presenter_heading_missing")
        # The page must not contain several distinct announced show dates
        # inside its primary event section. Repeated SAME date is fine.
        observed = {_date(t) for tag, t in section if tag in {
            "p", "time", "strong", "text", "div", "span", "h2", "h3", "h4", "h5"} and _date(t)}
        if observed != {when}:
            return held("primary_date_missing_or_ambiguous")
    else:
        dates = [_date(t) for tag, t in section[:16]
                 if tag in {"p", "time", "strong", "text", "div", "span"} and _date(t)]
        if not dates or dates[0] != when:
            return held("artist_heading_date_mismatch")
    # A complete field can be a paragraph or a generic leaf div. Inline
    # fragments and wrapper divs must not form synthetic event cards.
    paras = [t for tag, t in section if tag in {"p", "div"}]
    matches = {}
    for i in range(max(0, len(paras) - 3)):
        if _date(paras[i]) != when:
            continue
        bill = _artists(paras[i + 1])
        genre = CONCERT_GENRE.fullmatch(paras[i + 2])
        place = VENUE_ARROW.fullmatch(paras[i + 3])
        if (not bill or (names and [words(n) for n in bill] !=
                         [words(n) for n in names])
                or not genre or not place):
            continue
        label = visible._explicit_label(genre[1])
        if not label or _room_key(TRAILING_KIND.sub("", place[1]).strip()) != _room_key(room):
            continue
        key = (tuple(words(n) for n in bill), words(label))
        matches[key] = (bill, [label])
    if len(matches) != 1:
        return held("unique_date_bill_genre_room_card_missing")
    return next(iter(matches.values()))
