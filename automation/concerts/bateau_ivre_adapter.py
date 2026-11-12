"""Bateau Ivre (Tours, 37): bounded current programme and 2027 discovery.

The 2027 archive and current-month agenda are indexes, not evidence for genre. Exact individual
event pages must contain a dated masthead, named lineup and rock/punk/metal
genre before producing an *unapproved* review lead. No door time becomes a
musical start, no automatic publication. Do not crawl older archives.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit, quote, unquote, parse_qs

BASE = "https://www.bateauivre.coop"
ARCHIVE = BASE + "/2027/?post_type=events"
CURRENT = BASE + "/agenda-2/"
SLUG = re.compile(r"/evenements/([a-z0-9][a-z0-9-]{2,140})/")
MONTHS = {
    "jan": 1, "janvier": 1, "fev": 2, "fevrier": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7, "aou": 8, "aout": 8,
    "sep": 9, "sept": 9, "septembre": 9, "oct": 10,
    "octobre": 10, "nov": 11, "novembre": 11, "dec": 12,
    "decembre": 12,
}
DATE = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|"
    r"juillet|aout|septembre|sept|octobre|novembre|decembre|"
    r"jan|fev|avr|juil|aou|sep|oct|nov|dec)\.?\s+(20\d{2})\b"
)
GENRE = re.compile(
    r"\b(?:rock|punk|metal|grunge|shoegaze|stoner|sludge|"
    r"doom|post.rock|hardcore|noise rock|garage rock|"
    r"hard rock|ska punk)\b"
)
EXCLUDED = re.compile(
    r"\b(?:annule|annulation|reporte|festival|atelier|reunion|"
    r"conference|formation|stand.up|theatre|comedie|"
    r"improvisation|spectacle jeune public)\b"
)

def fold(s):
    return unicodedata.normalize("NFKD", unescape(str(s or "")).casefold()
                                   ).encode("ascii", "ignore").decode("ascii")

def normalize_detail(value):
    """Canonicalize the accented /évènements/ path, rejecting foreign URLs."""
    u = urlsplit(value)
    if (u.scheme != "https" or u.netloc != "www.bateauivre.coop"
            or u.username or u.password or u.port or u.query or u.fragment):
        return None
    path = fold(unquote(u.path))
    # The path in WordPress uses "évènements" (e-venements), not "events".
    m = SLUG.fullmatch(path)
    if not m or len(m[1]) > 140:
        return None
    final = "/%C3%A9v%C3%A8nements/" + m[1] + "/"
    return BASE + final

def valid_archive(url):
    u = urlsplit(url)
    return (u.scheme == "https" and u.netloc == "www.bateauivre.coop"
            and u.path == "/2027/" and parse_qs(u.query) == {"post_type": ["events"]}
            and not (u.fragment or u.username or u.password or u.port))

def valid_current(url):
    """Single current-month official programme, not historical archives."""
    u = urlsplit(url)
    return (u.scheme == "https" and u.netloc == "www.bateauivre.coop"
            and u.path == "/agenda-2/" and not (u.query or u.fragment
            or u.username or u.password or u.port))


class _Listing(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.urls = base, []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        link = normalize_detail(urljoin(self.base, href))
        if link and link not in self.urls:
            self.urls.append(link)

def archive_links(html, url):
    if not (valid_archive(url) or valid_current(url)):
        raise ValueError("Only pinned current programme or 2027 official index allowed")
    p = _Listing(url)
    p.feed(html)
    return p.urls

def select_urls(urls, known, today, limit=6, scan_slot=0):
    """Bounded, rotating first-party details with a stable daily recheck core.

    Three cloud passes/day inspect different official URLs without increasing
    pages per run. Two core detail URLs stay pinned across adjacent days so
    independent-day stability remains possible. This is *discovery only*.
    """
    amount = max(1, min(8, int(limit)))
    if scan_slot not in (0, 1, 2):
        raise ValueError("Unknown daily discovery scan slot")
    unique = sorted(set(x for x in urls if normalize_detail(x) == x))
    new = [x for x in unique if ("officialUrl", x) not in known]
    previous = [x for x in unique if ("officialUrl", x) in known]
    ordinal = dt.date.fromisoformat(today).toordinal()

    core_size = min(2, len(new), amount)
    anchor = ((ordinal // 2) * max(1, core_size)) % len(new) if new else 0
    core = [new[(anchor+i) % len(new)] for i in range(core_size)]
    remaining_new = [x for x in new if x not in core]
    room = amount - len(core)

    def rotate(pool, n):
        if not pool or n <= 0:
            return []
        # scan_slot ranges 0..2, producing different same-day pages while
        # keeping exact quotas and eliminating duplicate selected URLs.
        start = ((ordinal + scan_slot) * n) % len(pool)
        return [pool[(start+i) % len(pool)] for i in range(min(len(pool), n))]

    extra = rotate(remaining_new, room)
    rest = rotate(previous, room-len(extra))
    return core + extra + rest


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.h1_depth = 0
        self.h2_depth = 0
        self.skip = 0
        # Keep separate H1 positions. WordPress may repeat the same official
        # title before the detailed article; never concatenate different H1s.
        self.headings = []
        self._heading_parts = []
        self._subheading_parts = []
        self.support_headings = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.main_depth += 1
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.skip += 1
        if self.main_depth and not self.skip and tag == "h1":
            if self.h1_depth == 0:
                self._heading_parts = []
            self.h1_depth += 1
        if self.main_depth and not self.skip and tag == "h2":
            if self.h2_depth == 0:
                self._subheading_parts = []
            self.h2_depth += 1

    def handle_endtag(self, tag):
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1
            if self.h1_depth == 0:
                heading = " ".join(" ".join(self._heading_parts).split())
                if heading:
                    # Index of the first text piece following this exact H1.
                    self.headings.append((heading, len(self.parts)))
        if tag == "h2" and self.h2_depth:
            self.h2_depth -= 1
            if self.h2_depth == 0:
                heading = " ".join(" ".join(self._subheading_parts).split())
                if heading:
                    self.support_headings.append((heading, len(self.parts)))
        if tag in ("script", "style", "nav", "footer", "noscript") and self.skip:
            self.skip -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if not self.main_depth or self.skip or not data.strip():
            return
        if self.h1_depth:
            self._heading_parts.append(data)
        if self.h2_depth:
            self._subheading_parts.append(data)
        self.parts.append(data.strip())

def candidate(html, detail_url, source, today):
    clean = normalize_detail(detail_url)
    if clean is None or clean != detail_url:
        raise ValueError("Exact on-site canonical event detail URL required")
    if (source.get("name") not in ("Le Bateau Ivre",
                                     "Le Bateau Ivre — programme courant")
            or source.get("city") != "Tours"
            or source.get("department") != "37"
            or source.get("url") not in (CURRENT, ARCHIVE)):
        raise ValueError("Official source identity differs")
    p = _Detail()
    p.feed(html)
    if len(p.parts) < 5 or not p.headings:
        raise ValueError("Named event details unavailable")
    # An identical first-party H1 can be repeated by responsive templates.
    # Conflicting headings, however, make the event identity ambiguous.
    named = {fold(text) for text, _ in p.headings}
    if len(named) != 1:
        raise ValueError("Conflicting first-party event headings")
    title = p.headings[0][0]
    if not 4 <= len(title) <= 170 or EXCLUDED.search(fold(title)):
        raise ValueError("No named valid musical event masthead")
    header_title = fold(title)
    # Independent first-party support H2s may be placed BETWEEN the official
    # masthead H1 and its full event date. The old parser silently dropped
    # them, leaving an incomplete programme in the private review queue.
    # Only "+ ARTIST" H2 headings in this narrow event-header region count.
    first_end = p.headings[0][1]
    next_h1 = p.headings[1][1] if len(p.headings) > 1 else len(p.parts)
    bound = min(next_h1, first_end + 18, len(p.parts))
    first_date_end = next((
        pos for pos in range(first_end, bound)
        if DATE.search(fold(" ".join(p.parts[first_end:pos+1])))
    ), bound)
    supports = []
    for heading, end_pos in p.support_headings:
        if not (first_end < end_pos <= first_date_end):
            continue
        match = re.fullmatch(r"\s*\+\s*([^+]{2,100})\s*", heading)
        if not match:
            continue
        name = " ".join(match[1].split())
        if (not 2 <= len(name) <= 100
                or EXCLUDED.search(fold(name))):
            raise ValueError("Ambiguous first-party named support artist")
        if fold(name) not in header_title and name not in supports:
            supports.append(name)
    # These are placeholders, not performers. The heading may announce a
    # first part while withholding the actual band name.
    unannounced = {
        "premiere partie", "1ere partie", "1re partie", "guest", "guests",
        "special guest", "special guests", "invite", "invite surprise",
        "support", "a confirmer", "tba", "surprise",
    }
    supports = [name for name in supports if
                " ".join(re.findall(r"[a-z0-9]+", fold(name))) not in unannounced]
    if len(supports) > 3:
        raise ValueError("More than three support artists, review the programme")
    full_title = title
    if supports:
        full_title += " + " + " + ".join(supports)
        if len(full_title) > 200:
            raise ValueError("Official lineup longer than expected")
    # Read only the immediate text after EACH actual H1, not the first
    # ten snippets from <main> (which may contain navigation or hidden
    # header duplicates). Ignore years in artist bios or unrelated cards.
    dates = set()
    for _, end_pos in p.headings:
        near = fold(" ".join(p.parts[end_pos:end_pos + 8]))[:120]
        match = DATE.search(near)
        if not match:
            continue
        try:
            dates.add(dt.date(int(match[3]), MONTHS[match[2]], int(match[1])))
        except ValueError:
            raise ValueError("Impossible event date") from None
    if len(dates) != 1:
        raise ValueError("Missing or conflicting dated first-party masthead")
    date = dates.pop()
    anchor = dt.date.fromisoformat(today)
    if not anchor <= date <= anchor + dt.timedelta(days=365):
        raise ValueError("Past or distant event date")
    # The first-party detail must explicitly state rock, punk, metal or
    # adjacent sounds; "hardcore" alone may refer to electronic music.
    body = fold(" ".join(p.parts[:190]))[:7000]
    category = GENRE.search(body)
    if not category:
        raise ValueError("No official relevant musical genre")
    if category.group() == "hardcore" and not re.search(
            r"\b(?:punk|metal|rock|guitar)\b", body):
        raise ValueError("Unqualified hardcore could be techno")
    if EXCLUDED.search(body[:min(len(body), len(header_title)+180)]):
        raise ValueError("Cancelled or non-concert description")
    slug = SLUG.fullmatch(fold(unquote(urlsplit(clean).path)))[1]
    artist = re.split(r"\s+\+\s+", title, maxsplit=1)[0]
    return {
        "candidateId": "bateau-ivre:" + date.isoformat() + ":" + slug,
        "source": "bateau_ivre_official_detail_review",
        "sourceUrl": clean, "sourcePage": source["url"],
        "name": full_title, "leadArtist": artist,
        "firstPartyNamedSupport": supports,
        "date": date.isoformat(),
        "venue": "Le Bateau Ivre", "city": "Tours", "department": "37",
        "classification": [category.group()], "genreToConfirm": True,
        "officialDetailFound": True, "localTime": None,
        "sourceConfidence": "Fiche nominative officielle Tours : date avec année et genre; 19h30 est une heure d'accueil/billetterie, non un début musical. Relecture obligatoire.",
        "publicationAllowed": False, "reviewRequired": True,
    }
