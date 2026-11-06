"""Official, bounded Colmar/Grillen and Limoges/CCM John-Lennon discovery.

Only produces private *review leads*, NEVER approvals or direct publications.
A date without an explicitly written year is never assigned a year. Limoges
uses the municipality's dated agenda card; Grillen requires a dated detail.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit

GRILLEN = "https://grillen.colmar.fr"
GRILLEN_AGENDA = GRILLEN + "/agenda?date=toutes"
LIMOGES = "https://centresculturels.limoges.fr"
LIMOGES_AGENDA = LIMOGES + "/agenda?keys=hiero"
DETAIL_GRILLEN = re.compile(r"/programmation/([a-z0-9][a-z0-9-]{2,130})")
DETAIL_LIMOGES = re.compile(r"/agenda/([a-z0-9][a-z0-9-]{2,130})")
STOP = re.compile(
    r"\b(?:annule|annulation|reporte|reportee|festival|atelier|conference|"
    r"formation|reunion|jam session|spectacle jeune public)\b")
GENRE = re.compile(
    r"\b(?:metal|punk|rock|hardcore|post.rock|new wave|cold wave|"
    r"black metal|heavy blues|stoner|doom|sludge|noise|grunge|"
    r"shoegaze|indie rock|garage)\b")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
SHORT_MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aou": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11,
    "dec": 12,
}
MONTH_RE = "|".join(MONTHS)
FULL_DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])\s+(" + MONTH_RE + r")\s+(20\d{2})\b")
SHORT_DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])\s+([a-z]{3,4})\.?\s+(20\d{2})\b")
DAY_MONTH = re.compile(r"\b(0?[1-9]|[12]\d|3[01])\s+(" + MONTH_RE + r")\b")


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value or "")).casefold()
                                   ).encode("ascii", "ignore").decode("ascii")


def exact_detail(url, kind):
    u = urlsplit(url)
    host, path = ((GRILLEN, DETAIL_GRILLEN) if kind == "grillen"
                  else (LIMOGES, DETAIL_LIMOGES))
    base = urlsplit(host)
    if (u.scheme != "https" or u.netloc != base.netloc or u.port
            or u.username or u.password or u.query or u.fragment):
        return None
    m = path.fullmatch(u.path)
    return m[1] if m else None


def valid_agenda(url, kind):
    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.port or u.fragment:
        return False
    p = parse_qs(u.query, keep_blank_values=True)
    if kind == "grillen":
        return (u.netloc == "grillen.colmar.fr" and u.path == "/agenda"
                and p.get("date") == ["toutes"]
                and set(p) in ({"date"}, {"date", "page"})
                and ("page" not in p or p["page"] in (["0"], ["1"], ["2"])))
    return (u.netloc == "centresculturels.limoges.fr"
            and u.path == "/agenda" and p == {"keys": ["hiero"]})


class _Links(HTMLParser):
    def __init__(self, base, kind):
        super().__init__(convert_charrefs=True)
        self.urls = []
        self.base, self.kind = base, kind

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "a" or not attrs.get("href"):
            return
        url = urljoin(self.base, attrs["href"]).split("#")[0]
        if exact_detail(url, self.kind) and url not in self.urls:
            self.urls.append(url)


def grillen_links(html, listing_url):
    if not valid_agenda(listing_url, "grillen"):
        raise ValueError("Unknown or unbounded Grillen listing")
    p = _Links(listing_url, "grillen")
    p.feed(html)
    return p.urls


def select_urls(urls, known, today, limit=6):
    limit = max(1, min(9, int(limit)))
    unique = sorted(set(urls))
    unknown = [u for u in unique if ("officialUrl", u) not in known]
    already = [u for u in unique if ("officialUrl", u) in known]
    def rotate(pool, quota):
        if not pool or quota < 1:
            return []
        start = (dt.date.fromisoformat(today).toordinal() * quota) % len(pool)
        return [pool[(start + i) % len(pool)] for i in range(min(quota, len(pool)))]
    result = rotate(unknown, limit)
    return result + rotate(already, limit-len(result))


class _GrillenMain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.h1_depth = 0
        self.p_depth = 0
        self.h1 = []
        self.category = []
        self.blocks = []
        self.first_h1_end = None
        self._first_p = False
        self._script = 0

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.depth += 1
        if tag in ("script", "style", "noscript"):
            self._script += 1
        if self.depth:
            if tag == "h1":
                self.h1_depth += 1
            if tag == "p":
                self.p_depth += 1

    def handle_endtag(self, tag):
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1
            if self.h1_depth == 0 and self.first_h1_end is None:
                self.first_h1_end = len(self.blocks)
        if tag == "p" and self.p_depth:
            if not self._first_p and self.h1:
                self._first_p = True
            self.p_depth -= 1
        if tag in ("script", "style", "noscript") and self._script:
            self._script -= 1
        if tag == "main" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth or self._script or not data.strip():
            return
        self.blocks.append(data)
        if self.h1_depth:
            self.h1.append(data)
        elif self.p_depth and self.h1 and not self._first_p:
            self.category.append(data)


# Only exact, short, masthead category labels can recover a category from
# an official page with malformed P wrappers. Never search an artist bio.
FIRST_PARTY_MUSIC_LABELS = {
    "metal", "rock", "punk", "punk rock", "hard rock", "black metal",
    "post-rock", "new wave", "cold wave", "heavy blues",
    "stoner", "stoner rock", "doom", "sludge", "noise",
    "grunge", "shoegaze", "indie rock", "garage", "garage rock",
}


def grillen_detail(html, url, source, today):
    slug = exact_detail(url, "grillen")
    if not slug or (source.get("name"), source.get("city"),
                    source.get("department")) != ("Le Grillen", "Colmar", "68"):
        raise ValueError("Unrecognized official Colmar venue or URL")
    p = _GrillenMain()
    p.feed(html)
    title = " ".join(" ".join(p.h1).split())
    title = re.sub(r"\s+par\s*$", "", title, flags=re.I).strip()
    if not 4 <= len(title) <= 185 or STOP.search(fold(title)):
        raise ValueError("Cancelled, festival, workshop or unnamed concert")
    category = fold(" ".join(p.category))
    genre = GENRE.search(category)
    if not genre and p.first_h1_end is not None:
        # In real first-party markup the category may be a short sibling
        # text node rather than a clean <p>. Only the first four nodes
        # immediately following the event H1 are eligible, never prose.
        for piece in p.blocks[p.first_h1_end:p.first_h1_end + 4]:
            label = fold(piece).strip()
            if label in FIRST_PARTY_MUSIC_LABELS:
                category = label
                genre = GENRE.search(category)
                break
    if not genre:
        raise ValueError("No first-party music category in event masthead")
    full = fold(" ".join(p.blocks))
    if not re.search(r"\b(?:le )?grillen\b", full[:900]):
        raise ValueError("Exact room not attested in event header")
    # The masthead supplies day+month but *not necessarily year*.
    heading = fold(" ".join(p.h1))
    pos = full.find(heading)
    window = full[max(0, pos):max(0, pos)+1100]
    pair = DAY_MONTH.search(window)
    if not pair:
        raise ValueError("No official day and month in event header")
    # Year must be explicitly present in a first-party date expression,
    # linked to the venue in nearby context; never use footer/biography years.
    dated = []
    for m in FULL_DATE.finditer(window):
        context = window[max(0, m.start()-140):min(len(window), m.end()+50)]
        if re.search(r"\b(?:grillen|colmar)\b", context):
            try:
                day = dt.date(int(m[3]), MONTHS[m[2]], int(m[1]))
            except ValueError:
                raise ValueError("Invalid official calendar date") from None
            dated.append(day)
    if not dated:
        raise ValueError("Official individual page has no verified full year")
    if len(set(dated)) != 1:
        raise ValueError("Conflicting complete dates")
    date = dated[0]
    if (date.day, date.month) != (int(pair[1]), MONTHS[pair[2]]):
        raise ValueError("Detail full date conflicts with masthead day/month")
    ref = dt.date.fromisoformat(today)
    if not ref <= date <= ref + dt.timedelta(days=365):
        raise ValueError("Past or too distant event")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0]
    return {
        "candidateId": "grillen:" + date.isoformat() + ":" + slug,
        "name": title, "leadArtist": lead, "date": date.isoformat(),
        "venue": "Le Grillen", "city": "Colmar", "department": "68",
        "source": "grillen_official_detail_review", "sourceUrl": url,
        "sourcePage": GRILLEN_AGENDA, "classification": [genre.group()],
        "officialDetailFound": True, "genreToConfirm": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
        "sourceConfidence": "Grillen : date complète et catégorie sur fiche nominative; heures affichées non qualifiées, publication interdite.",
    }


class _LimogesCards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards, self.current = [], None
        self.article_level, self.h2_level, self.time_level = 0, 0, 0

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "article":
            if not self.article_level:
                self.current = {"text": [], "name": [], "time": [], "urls": [], "labels": []}
            self.article_level += 1
        if not self.article_level:
            return
        if tag == "h2":
            self.h2_level += 1
        if tag == "time":
            self.time_level += 1
            if props.get("datetime"):
                self.current["time"].append(props["datetime"])
        if tag == "a":
            if props.get("href"):
                self.current["urls"].append(props["href"])
            for key in ("title", "aria-label"):
                if props.get(key):
                    self.current["labels"].append(props[key])

    def handle_endtag(self, tag):
        if tag == "h2" and self.h2_level:
            self.h2_level -= 1
        if tag == "time" and self.time_level:
            self.time_level -= 1
        if tag == "article" and self.article_level:
            self.article_level -= 1
            if not self.article_level:
                self.cards.append(self.current)
                self.current = None

    def handle_data(self, text):
        if self.current is None or not text.strip():
            return
        self.current["text"].append(text)
        if self.h2_level:
            self.current["name"].append(text)
        if self.time_level:
            self.current["time"].append(text)


def limoges_cards(html, agenda_url, today):
    if not valid_agenda(agenda_url, "limoges"):
        raise ValueError("Only municipality's filtered Hiéro agenda accepted")
    p = _LimogesCards()
    p.feed(html)
    results = []
    ref = dt.date.fromisoformat(today)
    for c in p.cards:
        line = fold(" ".join(c["text"]))
        if "ccm john-lennon" not in line and "ccm john lennon" not in line:
            continue
        if "musique / concert" not in line or STOP.search(line):
            continue
        title = " ".join(" ".join(c["name"]).split())
        if not title:
            title = next((x for x in c["labels"] if len(x.strip()) > 5), "")
        if not 4 <= len(title) <= 160 or STOP.search(fold(title)):
            continue
        dated = set()
        time_str = fold(" ".join(c["time"]))
        for regex, months in ((FULL_DATE, MONTHS), (SHORT_DATE, SHORT_MONTHS)):
            for match in regex.finditer(time_str):
                if match[2] not in months:
                    continue
                try:
                    dated.add(dt.date(int(match[3]), months[match[2]],
                                      int(match[1])))
                except ValueError:
                    pass
        for iso in re.findall(r"\b20\d{2}-[01]\d-[0-3]\d\b", time_str):
            try:
                dated.add(dt.date.fromisoformat(iso))
            except ValueError:
                pass
        if len(dated) != 1:
            continue
        date = dated.pop()
        if not ref <= date <= ref + dt.timedelta(days=365):
            continue
        urls = sorted({
            urljoin(agenda_url, href).split("#")[0] for href in c["urls"]
            if exact_detail(urljoin(agenda_url, href).split("#")[0], "limoges")
        })
        if len(urls) != 1:
            continue
        results.append({
            "date": date.isoformat(), "title": title, "url": urls[0],
            "venue": "CCM John-Lennon", "city": "Limoges",
        })
    return results


def limoges_detail(html, card, source, today):
    url = card["url"]
    slug = exact_detail(url, "limoges")
    if not slug or (source.get("name"), source.get("city"),
                    source.get("department")) != (
                        "Espace John Lennon", "Limoges", "87"):
        raise ValueError("Foreign municipality or unexpected venue")
    # The *agenda card* alone gives the full date and exact room.
    # The detail corroborates the headline and a relevant musical genre;
    # a page publication timestamp (RSS/HTML) is never an event date.
    p = _GrillenMain()
    p.feed(html)
    article = fold(" ".join(p.blocks))
    if not article:
        other = re.sub(r"<[^>]+>", " ", html)
        article = fold(other)
    og = re.search(r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
    fullpage = fold(html)
    title = fold(card["title"])
    if title not in article and not (og and title in fold(og[1])):
        # Some city templates put the heading outside <main>. Accept its
        # exact headline elsewhere in the first-party HTML, not a guess.
        if title not in fullpage:
            raise ValueError("Individual page does not confirm listing title")
    genre = GENRE.search(article)
    if not genre:
        raise ValueError("No official genre on individual municipal concert page")
    if STOP.search(fold(card["title"])) or STOP.search(article[:300]):
        raise ValueError("Cancelled or non-concert page")
    date = dt.date.fromisoformat(card["date"])
    ref = dt.date.fromisoformat(today)
    if not ref <= date <= ref + dt.timedelta(days=365):
        raise ValueError("Past or beyond horizon")
    lead = re.sub(r"^release party\s*:\s*", "", card["title"], flags=re.I)
    lead = re.split(r"\s+\+\s+", lead, maxsplit=1)[0]
    return {
        "candidateId": "limoges-john-lennon:" + card["date"] + ":" + slug,
        "name": card["title"], "leadArtist": lead, "date": card["date"],
        "venue": "Espace John Lennon", "city": "Limoges", "department": "87",
        "source": "limoges_municipal_card_detail_review",
        "sourceUrl": url, "sourcePage": LIMOGES_AGENDA,
        "classification": [genre.group()], "genreToConfirm": True,
        "officialDetailFound": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
        "sourceConfidence": "Carte agenda municipale : date complète et lieu John-Lennon; fiche individuelle : titre et genre. Relecture exigée, pas d'heure musicale inférée.",
    }
