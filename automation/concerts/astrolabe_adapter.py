"""L'Astrolabe Orléans: official homepage to individual-event leads only.

The full /agenda/ mixes 2017 archives with current dates. Read the curated
homepage instead and require a dated individual page with an explicit
genre, first-party address and venue-room label. NEVER publish or infer
the show start from a displayed clock (often door opening).
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOME = "https://www.lastrolabe.org/"
HOSTS = {"www.lastrolabe.org", "lastrolabe.org"}
EVENT = re.compile(r"/agenda/([a-z0-9][a-z0-9-]{2,120})/")
DATE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.(20\d{2})\s*-\s*([012]?\d)[hH](\d{2})\b")
GENRE = re.compile(r"\b(?:metal|hardcore|punk|rock|noise|grunge|shoegaze|stoner|sludge|doom|thrash|garage|post[- ]rock|blackgaze)\b", re.I)
VENUE = re.compile(r"\b(?:grande salle|le club|astroclub|l.astrolabe)\b", re.I)
STOP = re.compile(r"\b(?:annul[eé]e?|report[eé]e?|d[eé]plac[eé]e?|cancelled|postponed)\b",re.I)


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value)).casefold()).encode(
        "ascii", "ignore").decode("ascii")


def valid_detail(value):
    u = urlsplit(value)
    if (u.scheme != "https" or u.hostname not in HOSTS or u.port
            or u.username or u.password or u.query or u.fragment):
        return None
    m = EVENT.fullmatch(u.path)
    return m[1] if m else None


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.tokens = []
        self.main_depth = 0
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "main":
            self.main_depth += 1
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.hidden += 1
        if tag == "a":
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "nav", "footer", "noscript") and self.hidden:
            self.hidden -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if not self.main_depth or self.hidden:
            return
        token = " ".join(data.split())
        if token:
            self.tokens.append(token)


def detail_urls(html, listing_url):
    u = urlsplit(listing_url)
    if u.scheme != "https" or u.hostname not in HOSTS or u.path not in ("/", ""):
        raise ValueError("Astrolabe official homepage required; no archive scan")
    p = _Visible()
    p.feed(html)
    return sorted({
        url for href in p.links
        if (url := urljoin(listing_url, href)) and valid_detail(url)
    })


def selected_urls(urls, known, day, limit=8):
    """Bounded rotation: unknown URLs first, published pages also rechecked."""
    day = dt.date.fromisoformat(day)
    limit = max(1, min(12, int(limit)))
    unique = sorted(set(urls))
    unseen = [url for url in unique if ("officialUrl", url) not in known]
    known_urls = [url for url in unique if ("officialUrl", url) in known]

    def rotate(pool, quota):
        if not pool or quota <= 0:
            return []
        amount = min(len(pool), quota)
        start = (day.toordinal() * amount) % len(pool)
        return [pool[(start+i) % len(pool)] for i in range(amount)]
    result = rotate(unseen, limit)
    result += rotate(known_urls, limit-len(result))
    return result


def detail_candidate(html, url, source, today):
    slug = valid_detail(url)
    if slug is None:
        raise ValueError("Official individual Astrolabe event URL required")
    if (source.get("name") != "L'Astrolabe"
            or source.get("city") != "Orléans"
            or source.get("department") != "45"):
        raise ValueError("Unexpected venue identity")
    p = _Visible()
    p.feed(html)
    if len(p.tokens) < 3:
        raise ValueError("No event details in main")
    # The concert masthead precedes the biography. Only the FIRST
    # explicitly year-qualified event date in the page header counts.
    head = p.tokens[:75]
    date_index = next((i for i, t in enumerate(head) if DATE.search(fold(t))), None)
    if date_index is None or date_index > 20:
        raise ValueError("Missing first-party dated event header")
    dateline = " ".join(head[date_index:date_index+4])
    m = DATE.search(fold(dateline))
    if not m:
        raise ValueError("Invalid event date")
    try:
        event_day = dt.date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        raise ValueError("Invalid calendar date") from None
    scan_date = dt.date.fromisoformat(today)
    if not scan_date <= event_day <= scan_date+dt.timedelta(days=365):
        raise ValueError("Past or out-of-horizon event")
    if not VENUE.search(fold(dateline[m.end():m.end()+100])):
        raise ValueError("Astrolabe room not explicitly specified")
    prefix = head[:date_index]
    genre_index = next((i for i,t in enumerate(prefix[:12])
                        if 2 <= len(t) <= 80 and GENRE.search(fold(t))), None)
    if genre_index is None:
        raise ValueError("No first-party rock/metal/punk genre")
    genre = prefix[genre_index].strip()
    title = " ".join(prefix[genre_index+1:]).strip()
    title = re.sub(r"\s*\+\s*", " + ", title)
    if not 3 <= len(title) <= 160:
        raise ValueError("No valid artist bill before date")
    if STOP.search(fold(" ".join(head[:date_index+5]))):
        raise ValueError("Cancelled or postponed concert")
    lead = title.split(" + ", 1)[0].strip()
    if not lead or not re.search(r"[a-zA-Z]", fold(lead)):
        raise ValueError("No named lead artist")
    return {
        "candidateId": f"astrolabe:{event_day.isoformat()}:{slug}",
        "name": title, "leadArtist": lead, "date": event_day.isoformat(),
        "venue": "L'Astrolabe", "city": "Orléans", "department": "45",
        "classification": [genre], "genreEvidence": "official_event_header",
        "genreToConfirm": False,
        "source": "agenda_officiel_astrolabe_detail_review",
        "sourcePage": source["url"], "sourceUrl": url,
        "sourceConfidence": (
            "Détail officiel Astrolabe: genre, affiche et date/lieu complets. "
            "Horaire non converti en début; approbation distincte obligatoire."),
        "officialDetailFound": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
    }
