"""Conservative first-party *individual event* discovery: Backstage BTM + Forum.

List pages are URL directories only. No event data is accepted without reading
the actual same-host detail and finding unambiguous date, genre, headline and
venue. Forum details with just day/month are deliberately rejected; no year
inference from "upcoming", site copyright, timestamps, or today's date.
These are READ-ONLY leads, never approvals or publication.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOSTS = {
    "backstage": ("www.backstage-btm.com", "/agenda/"),
    "forum": ("leforum.cergypontoise.fr", "/agenda/"),
}
MONTHS = dict(zip(
    ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
     "aout", "septembre", "octobre", "novembre", "decembre"),
    range(1, 13)))
FR_DATE = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b", re.I)
NUM_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)")
MUSIC = re.compile(
    r"\b(metal|metalcore|deathcore|blackgaze|grindcore|hardcore|"
    r"punk|stoner|sludge|doom|thrash|hard rock|heavy metal|post rock|"
    r"post metal)\b", re.I)
PROHIBITED = re.compile(
    r"\b(annul[eé]|annul[eé]e|annulation|report[eé]|report[eé]e|"
    r"cancelled|canceled|postponed|report du concert)\b", re.I)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                               value.encode("ascii", "ignore").decode("ascii")))


def exact_detail_url(url, kind):
    host, prefix = HOSTS[kind]
    target = urlsplit(url)
    return bool(target.scheme == "https" and target.hostname == host
                and not target.username and not target.password and
                not target.port and not target.query and not target.fragment
                and re.fullmatch(re.escape(prefix) + r"[a-z0-9-]+/?",
                                 target.path, flags=re.I))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = dict(attrs).get("href")
            if url:
                self.hrefs.append(url)


def detail_urls(listing_html, base_url, kind, cap=100):
    host, path = HOSTS[kind]
    base = urlsplit(base_url)
    if (base.scheme != "https" or base.hostname != host or
        base.path.rstrip("/") != path.rstrip("/") or
        base.query or base.fragment or base.username or base.password):
        raise ValueError("Official listing URL unexpected")
    parser = Links()
    parser.feed(listing_html)
    urls, seen = [], set()
    for href in parser.hrefs:
        url = urljoin(base_url, href)
        if exact_detail_url(url, kind) and url not in seen:
            urls.append(url)
            seen.add(url)
        if len(urls) >= cap:
            break
    return urls


class MainText(HTMLParser):
    """Collect only first-party main content; navigation/scripts are ignored."""
    VOID = {"br","img","input","meta","link","hr","source","area","wbr"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.hidden = 0
        self.active = None
        self.parts = []
        self.records = []
        self.pre_heading = []
        self.seen_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "main" and self.depth == 0:
            self.depth = 1
            return
        if not self.depth:
            return
        if tag not in self.VOID:
            self.depth += 1
        if tag in ("script","style","noscript"):
            self.hidden += 1
        if not self.hidden and tag in ("h1","h2","p") and self.active is None:
            self.active = (tag, self.depth)
            self.parts = []
    def handle_startendtag(self, tag, attrs):
        pass
    def handle_data(self, data):
        if not self.depth or self.hidden:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self.active:
            self.parts.append(value)
        elif not self.seen_h1:
            self.pre_heading.append(value)
    def handle_endtag(self, tag):
        if not self.depth:
            return
        if self.active and tag == self.active[0] and self.depth == self.active[1]:
            value = " ".join(self.parts).strip()
            if value:
                self.records.append((tag,value))
            if tag == "h1":
                self.seen_h1 = True
            self.active = None
            self.parts = []
        if tag in ("script","style","noscript") and self.hidden:
            self.hidden -= 1
        if tag not in self.VOID:
            self.depth -= 1


def date_number(value):
    m = NUM_DATE.fullmatch(norm(value).replace(" ", "/"))  # unused safe fallback
    # Format as actually rendered by Backstage: DD/MM/YYYY.
    m = NUM_DATE.search(value)
    if not m:
        return None
    try:
        return dt.date(int(m[3]),int(m[2]),int(m[1]))
    except ValueError:
        return None


def forum_date(record_text):
    """Full French year must occur in a short, explicit event/venue sentence."""
    for text in record_text:
        if (len(text) > 300 or not re.search(
                r"\b(forum|rendez.vous|concert|scene|scène)\b", norm(text))):
            continue
        for match in FR_DATE.finditer(norm(text)):
            day, month, year = match.groups()
            try:
                return dt.date(int(year), MONTHS[month], int(day))
            except ValueError:
                continue
    return None


def detail_candidate(html_text, url, venue, today, kind):
    """Never infer a date, genre or artist from a generic agenda or biography."""
    if kind not in HOSTS or not exact_detail_url(url,kind):
        raise ValueError("Official single-event URL required")
    if ((kind == "backstage" and
         (venue.get("name") != "Backstage By The Mill" or venue.get("city") != "Paris"))
        or (kind == "forum" and
            (venue.get("name") != "Le Forum de Vauréal" or venue.get("city") != "Vauréal"))):
        raise ValueError("Venue registry identity mismatch")
    page=MainText()
    page.feed(html_text)
    first_h1 = [i for i,(tag,_) in enumerate(page.records) if tag == "h1"]
    if len(first_h1) != 1:
        raise ValueError("Missing or ambiguous event headline")
    pos=first_h1[0]
    title=page.records[pos][1]
    first = [value for tag,value in page.records[pos+1:]
             if tag == "p"][:9]
    prefix = [value for tag,value in page.records[pos+1:]
              if tag == "p"][:5]
    if not (3 <= len(norm(title)) <= 180) or PROHIBITED.search(norm(title)):
        raise ValueError("Invalid or cancelled headline")
    # An explicit cancellation next to event metadata takes precedence over
    # any date/genre. Later tour history or song titles are not event states.
    if any(PROHIBITED.search(norm(text)) for text in prefix[:4]):
        raise ValueError("Event cancelled or postponed")
    if kind == "backstage":
        if len(first)<3:
            raise ValueError("Incomplete event header")
        label = norm(first[0])
        event_date = date_number(first[1])
        location = norm(first[2])
        if not event_date or not ("mill" in location and "paris" in location):
            raise ValueError("Full date or venue on official detail missing")
    else:
        label = norm(" ".join(page.pre_heading[-16:]))
        # Genre is in a narrow official category label ahead of the h1.
        # Avoid words elsewhere in the artist biography.
        if not label or len(label)>250:
            raise ValueError("Genre badges absent or ambiguous")
        event_date = forum_date(first[:6])
        venue_confirmed = any(
            "le forum" in norm(value) for value in first[:5])
        if not venue_confirmed:
            raise ValueError("Forum venue not explicitly named on event")
        if not event_date:
            raise ValueError("Full year missing from official event text")
    if not MUSIC.search(label):
        raise ValueError("No explicit punk/metal/rock genre badge")
    if event_date < dt.date.fromisoformat(str(today)):
        raise ValueError("Event in the past")
    # Exact detail URL + human-readable full date; no event time inferred
    # from opening doors or ticketing.
    slug = urlsplit(url).path.strip("/").split("/")[-1]
    candidate = {
        "candidateId": kind + ":" + event_date.isoformat() + ":" + slug,
        "source": ("agenda_officiel_backstage_detail" if kind == "backstage"
                   else "agenda_officiel_forum_detail"),
        "sourceUrl": url,
        "sourcePage": venue["url"],
        "date": event_date.isoformat(),
        "localTime": None,
        "name": title,
        "leadArtist": title,
        "venue": venue["name"],
        "city": venue["city"],
        "department": venue["department"],
        "classification": [label],
        "genreToConfirm": False,
        "publicationAllowed": False,
        "reviewRequired": True,
        "sourceConfidence": (
            "Fiche individuelle officielle : date complète, genre et lieu ; "
            "artistes et heure à confirmer avant toute publication"
        ),
    }
    return candidate
