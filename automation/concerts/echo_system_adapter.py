"""Echo System official-venue concerts: independent dated detail leads only.

The public agenda hides the YEAR in its cards. Do not infer it from the
current month or web cache: only an individual first-party event-detail
page with a full year, title, genre and exact venue can create a dated lead.
No records returned here authorize publication or auto-approval.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOST = "echosystem70.fr"
VENUE_ID = "echo-system-scey"
EVENT_PATH = re.compile(r"/evenement/[a-z0-9-]{3,140}/?")
MONTHS = {
    "janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12,
}
DATE = re.compile(r"\b(\d{1,2})\s+("
                  + "|".join(MONTHS) + r")\s+(20\d{2})\b")
CLOCK = re.compile(r"\b((?:[01]?\d|2[0-3]))\s*[hH]\s*([0-5]\d)\b")
GENRE = re.compile(r"\b(metal|punk|hardcore|thrash|doom|sludge|stoner|"
                   r"grind|deathcore|hard rock)\b")
EXCLUDED = re.compile(r"\b(festival|fest|masterclass|atelier|concours|blindtest|"
                      r"open air|annule|annulee|reporte|reportee|dj set|tba)\b")
VOID = {"br","img","meta","link","hr","input","source","area"}


def flat(value):
    return (unicodedata.normalize("NFKD", str(value or "")).encode("ascii","ignore")
            .decode("ascii").lower())


def norm(value):
    return " ".join(re.findall(r"[a-z0-9]+", flat(value)))


def safe_event_url(href, base):
    url = urljoin(base, href)
    p = urlsplit(url)
    if (p.scheme == "https" and p.hostname in (HOST, "www."+HOST)
            and not p.username and not p.password and not p.query
            and not p.fragment and EVENT_PATH.fullmatch(p.path)):
        return url
    return None


class AgendaLinks(HTMLParser):
    """Links within official .evt cards, not arbitrary footer recommendations."""
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.depth = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        params = dict(attrs)
        if self.depth:
            if tag not in VOID:
                self.depth += 1
            if tag == "a":
                link = safe_event_url(params.get("href") or "", self.base)
                if link and link not in self.links:
                    self.links.append(link)
        elif tag == "div" and "evt" in (params.get("class") or "").split():
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag not in VOID:
            self.depth -= 1


class OfficialDetail(HTMLParser):
    FIELDS = {"titevt":"title", "sstitevt":"genre",
              "ladateevt":"date", "lelieu":"venue"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.depth = 0
        self.parts = []
        self.fields = {key:[] for key in self.FIELDS.values()}

    def handle_starttag(self, tag, attrs):
        p = dict(attrs)
        if self.current is not None:
            if tag not in VOID:
                self.depth += 1
            return
        classes = (p.get("class") or "").split()
        field = next((self.FIELDS[x] for x in classes if x in self.FIELDS), None)
        field = field or self.FIELDS.get(p.get("id"))
        if field:
            self.current, self.depth, self.parts = field, 1, []

    def handle_endtag(self, tag):
        if self.current is None or tag in VOID:
            return
        self.depth -= 1
        if self.depth == 0:
            value = " ".join(" ".join(self.parts).split())
            if value:
                self.fields[self.current].append(value)
            self.current, self.parts = None, []

    def handle_data(self, data):
        if self.current is not None:
            self.parts.append(data)


def official_links(page, base):
    parser=AgendaLinks(base)
    parser.feed(page)
    return parser.links


def detail_candidate(page, url, venue, today):
    if not safe_event_url(url, url):
        raise ValueError("Adresse d'événement hors domaine officiel")
    doc=OfficialDetail()
    doc.feed(page)
    if any(len(v)!=1 for v in doc.fields.values()):
        raise ValueError("Titre, genre, date ou salle officielle ambiguë")
    title, genre, day_text, location = (
        doc.fields["title"][0], doc.fields["genre"][0],
        doc.fields["date"][0], doc.fields["venue"][0]
    )
    if (not 4<=len(title)<=200 or EXCLUDED.search(norm(title))
            or EXCLUDED.search(norm(genre)) or not GENRE.search(norm(genre))):
        raise ValueError("Affiche non concert ou genre métal/punk non explicite")
    if not re.search(r"\becho system\b", norm(location)):
        raise ValueError("Concert dans une autre salle")
    if norm(venue.get("name"))!="echo system" or norm(venue.get("city"))!="scey sur saone et saint albin":
        raise ValueError("Configuration de lieu non correspondante")
    dates=DATE.findall(flat(day_text))
    hours=CLOCK.findall(day_text)
    if len(dates)!=1 or len(hours)!=1:
        raise ValueError("Année ou heure officielle absente / ambiguë")
    d,m,y = dates[0]
    when=dt.date(int(y),MONTHS[m],int(d))
    if when < dt.date.fromisoformat(str(today)):
        raise ValueError("Événement passé")
    hour,minute=hours[0]
    clean_title=" ".join(title.split())
    slug=re.sub(r"[^a-z0-9]+","-",flat(clean_title)).strip("-")[:90]
    if not slug:
        raise ValueError("Identifiant de concert inexploitable")
    head=clean_title.split(":",1)[-1].split("+",1)[0].strip()
    return {
        "candidateId":f"echo-system:{when.isoformat()}:{slug}",
        "source":"agenda_officiel_echo_system_genre",
        "sourceUrl":url,"sourcePage":venue["url"],
        "name":clean_title,"leadArtist":head,
        "date":when.isoformat(),"localTime":f"{int(hour):02d}:{minute}",
        "venue":"Echo System","venueCatalogueId":VENUE_ID,
        "city":venue["city"],"department":venue["department"],
        "classification":[genre],"genreToConfirm":False,
        "officialDetailFound":True,"reviewRequired":True,
        "publicationAllowed":False,
        "sourceConfidence":"Fiche individuelle Echo System : date, genre et lieu indiqués, publication interdite avant contrôle indépendant"
    }
