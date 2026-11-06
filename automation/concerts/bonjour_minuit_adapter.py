"""Bonjour Minuit (Saint-Brieuc): first-party discovery, NEVER approval.

The public agenda is a bounded index of individual /evenement/ links.
Only a named official detail may prove date, venue and relevant genre.
No year is inferred from a URL, current date, tour or biography. The venue
explicitly states that listed times are DOOR times; even its stage-running
orders may be indicative, and are never promoted to musical start times.
The Club is a valid concert room. Other rooms, offsite events and festivals
are held. This module does not write a public catalogue or approvals.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://bonjour-minuit.fr/agenda/"
HOST = "bonjour-minuit.fr"
DETAIL_PATH = re.compile(r"/evenement/([a-z0-9][a-z0-9-]{2,115})/", re.I)
MONTHS = dict(zip(
    "janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre".split(),
    range(1, 13),
))
DATE = re.compile(r"\b([0-3]?\d)\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b")
ROOM = re.compile(r"\b(grande salle|club)\b")
NONCONCERT = re.compile(
    r"\b(rencontre|session d ecoute|session live radio|emission de radio|"
    r"conference|atelier|formation|spectacle jeune public|visite|"
    r"residence|stage|masterclass|exposition|festival|open air)\b")
CANCEL = re.compile(r"\b(annule|annulee|annulation|cancelled|canceled)\b")
POSTPONE = re.compile(r"\b(reporte|reportee|report|postponed|rescheduled)\b")
SOLD_OUT = re.compile(r"\b(complet|complete|sold out)\b")
# The style must be an explicit label *immediately following a named artist
# heading* on the individual venue page. A bio, venue menu and a "Si vous aimez"
# paragraph do NOT qualify.
STYLE = re.compile(
    r"\b(rock progressif|rock inde|rock alternatif|post rock|post metal|"
    r"garage rock|noise rock|stoner|sludge|shoegaze|hardcore|metalcore|"
    r"death metal|black metal|doom|punk|grunge|psychedelique|garage|"
    r"metal|rock)\b")


def plain(value):
    s = unicodedata.normalize("NFKD", unescape(str(value or "")))
    return " ".join(re.findall(
        r"[a-z0-9]+", s.casefold().encode("ascii", "ignore").decode("ascii")))


def valid_agenda(url):
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == HOST
            and p.path == "/agenda/" and not (p.query or p.fragment
            or p.port or p.username or p.password))


def detail_url(href, base=AGENDA):
    if not isinstance(href, str):
        return None
    u = urljoin(base, href)
    p = urlsplit(u)
    if (p.scheme != "https" or p.hostname != HOST or p.port
            or p.username or p.password or p.query or p.fragment
            or not DETAIL_PATH.fullmatch(p.path)
            or p.path.lower() in ("/evenement/archives/", "/evenement/agenda/")):
        return None
    return u


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            url = detail_url(dict(attrs).get("href"))
            if url and url not in self.hrefs:
                self.hrefs.append(url)


def agenda_links(html, url=AGENDA):
    if not valid_agenda(url):
        raise ValueError("Only the official Bonjour Minuit first page is authorized")
    parser = Links()
    parser.feed(html)
    return parser.hrefs


def choose(urls, known, today, limit=8):
    """One daily bounded slice, prioritizing new dates but revisiting published."""
    limit = max(1, min(10, int(limit)))
    unique = list(dict.fromkeys(urls))
    pending = [u for u in unique if ("officialUrl", u) not in known]
    existing = [u for u in unique if ("officialUrl", u) in known]
    day = dt.date.fromisoformat(today).toordinal()

    def rotating(items, n):
        if not items or n <= 0:
            return []
        count = min(n, len(items))
        start = day % len(items)
        return [items[(start + i) % len(items)] for i in range(count)]

    fresh = rotating(pending, (limit + 1) // 2 if existing else limit)
    revisits = rotating(existing, limit - len(fresh))
    more = rotating([u for u in pending if u not in fresh],
                    limit - len(fresh) - len(revisits))
    return fresh + revisits + more


class Detail(HTMLParser):
    """First-party named headings with separately bounded visible context.

    Real venue HTML uses DIV/SPAN elements for the event date, hall and
    artist's genre badge. They are NOT necessarily <p> elements. Preserve
    those visible fields *only between* the named H1 and first artist H2,
    and between that H2 and the start of the artist biography, respectively.
    Footer, cookie banners and biographies cannot contribute genre evidence.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.current = None
        self.hidden = 0
        self.sup = 0
        self.seen_h1 = False
        self.seen_first_h2 = False
        self.closed_first_h2 = False
        self.first_bio_started = False
        self.header_chunks = []
        self.first_style_chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.hidden += 1
        if tag == "sup":
            self.sup += 1
        if tag == "h2" and self.seen_h1 and not self.seen_first_h2:
            self.seen_first_h2 = True
        if tag == "p" and self.closed_first_h2 and not self.first_bio_started:
            self.first_bio_started = True
        if self.current is None and not self.hidden and tag in ("h1", "h2", "p"):
            self.current = {"tag": tag, "pieces": []}

    def handle_data(self, data):
        if self.hidden or self.sup:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self.current is not None:
            self.current["pieces"].append(value)
        if self.seen_h1 and not self.seen_first_h2:
            self.header_chunks.append(value)
        if self.closed_first_h2 and not self.first_bio_started:
            self.first_style_chunks.append(value)

    def handle_endtag(self, tag):
        if self.current is not None and tag == self.current["tag"]:
            text = " ".join(self.current["pieces"]).strip()
            if text:
                self.nodes.append((tag, text))
            self.current = None
            if tag == "h1":
                self.seen_h1 = True
        if tag == "h2" and self.seen_first_h2 and not self.closed_first_h2:
            self.closed_first_h2 = True
        if tag == "sup" and self.sup:
            self.sup -= 1
        if tag in ("script", "style", "nav", "footer", "noscript") and self.hidden:
            self.hidden -= 1


def full_dates(text):
    dates = set()
    for d, month, y in DATE.findall(plain(text)):
        try:
            dates.add(dt.date(int(y), MONTHS[month], int(d)).isoformat())
        except ValueError:
            continue
    return dates


def candidate(html, url, source, today):
    if (detail_url(url) != url
            or source.get("name") != "Bonjour Minuit"
            or source.get("city") != "Saint-Brieuc"
            or str(source.get("department")) != "22"
            or source.get("url") != AGENDA):
        raise ValueError("Source, salle, département ou URL invalide")
    parsed = Detail()
    parsed.feed(html)
    nodes = parsed.nodes
    headings = [i for i, (tag, _) in enumerate(nodes) if tag == "h1"]
    if len(headings) != 1:
        raise ValueError("En-tête individuel manquant ou ambigu")
    i = headings[0]
    title = nodes[i][1]
    if not 3 <= len(title) <= 200 or NONCONCERT.search(plain(title)):
        raise ValueError("Format hors concerts ou intitulé invalide")
    # Bounded section after event H1 and BEFORE the first named artist H2:
    # the site uses DIV and SPAN for date, room and door hours.
    header = plain(" ".join(parsed.header_chunks))
    bounded = re.split(r"\b(?:tarifs|placement|si vous aimez|billetterie)\b",
                       header, maxsplit=1)[0][:1200]
    dates = full_dates(bounded)
    if len(dates) != 1:
        raise ValueError("Année complète absente de l'en-tête officiel")
    date = next(iter(dates))
    start_day = dt.date.fromisoformat(today)
    if not start_day <= dt.date.fromisoformat(date) <= start_day + dt.timedelta(days=540):
        raise ValueError("Date hors horizon")
    rooms = {m.group(1) for m in ROOM.finditer(bounded)}
    if len(rooms) != 1 or NONCONCERT.search(plain(title)):
        raise ValueError("Grande Salle ou Club non confirmé dans l'en-tête")
    hall = "Le Club" if rooms == {"club"} else "La Grande Salle"
    # An official artist badge immediately after the first H2 is the
    # only admissible Rock evidence. It is not an artist biography
    # and not a venue-wide navigation tag.
    first_h2 = next((n for n in range(i+1,len(nodes))
                     if nodes[n][0]=="h2"), None)
    if first_h2 is None:
        raise ValueError("Artiste nommément identifié manquant")
    first_name = nodes[first_h2][1]
    if not plain(first_name) or plain(first_name) not in plain(title):
        raise ValueError("Artiste de la fiche différent du titre du concert")
    style_text = plain(" ".join(parsed.first_style_chunks))[:95]
    if not style_text and first_h2+1 < len(nodes) and nodes[first_h2+1][0]=="p":
        # Older or test markup uses a short P for the artist badge.
        short = nodes[first_h2+1][1]
        if len(short) <= 85:
            style_text = plain(short)
    found = STYLE.search(style_text)
    if not found or found.start() != 0:
        raise ValueError("Étiquette officielle Rock/Metal/Punk absente")
    genres = [found.group(1).title()]
    lead_artist = re.sub(r"\s+release party$", "", first_name, flags=re.I).strip()
    state = ("cancelled" if CANCEL.search(bounded)
             else "postponed" if POSTPONE.search(bounded)
             else "sold_out" if SOLD_OUT.search(bounded)
             else "confirmed_unchecked")
    door = None
    door_matches = re.findall(
        r"\b(\d{1,2})\s*h\s*([0-5]\d)\s+ouverture des portes\b", bounded)
    if len(door_matches) == 1:
        door = f"{int(door_matches[0][0]):02d}:{door_matches[0][1]}"
    if not door:
        displayed = re.search(
            r"\b(?:grande salle|club)\s+(\d{1,2})\s*h\s*([0-5]\d)\b",
            bounded)
        if displayed:
            door = f"{int(displayed.group(1)):02d}:{displayed.group(2)}"
    slug = DETAIL_PATH.fullmatch(urlsplit(url).path).group(1)
    return {
        "candidateId": f"bonjourminuit:{date}:{slug}",
        "name": title, "leadArtist": lead_artist,
        "date": date, "venue": "Bonjour Minuit",
        "venueCatalogueId": "bonjour-minuit-saint-brieuc",
        "venueHall": hall, "city": "Saint-Brieuc", "department": "22",
        "classification": genres, "genreEvidenceScope": "official_artist_in_event_detail",
        "officialDetailFound": True,
        "source": "agenda_officiel_bonjour_minuit_detail_review",
        "sourcePage": AGENDA, "sourceUrl": url,
        "doorTime": door, "localTime": None,
        "timeMeaning": "unverified_music_start",
        "statusNotice": state, "soldOutNotice": state == "sold_out",
        "cancellationNotice": state in ("cancelled", "postponed"),
        "sourceConfidence": "Named first-party date, venue and artist style; start times unverified",
        "reviewRequired": True, "publicationAllowed": False,
    }
