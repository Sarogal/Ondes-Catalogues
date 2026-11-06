"""Le Molotov (Marseille) — adaptation du calendrier officiel HTML.
L'extraction sert à découvrir des pistes, jamais à les publier.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
import urllib.parse

MONTHS = {
    "jan": 1, "fev": 2, "fév": 2, "mar": 3, "avr": 4, "mai": 5,
    "jun": 6, "juin": 6, "jul": 7, "juil": 7, "aou": 8, "aoû": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12
}
TIME = re.compile(r"\b(\d{1,2})[:h](\d{2})\b", re.I)
STRICT_MUSIC = ("metal", "metalcore", "deathcore", "hardcore", "punk",
                "doom", "sludge", "grind", "stoner", "hard rock",
                "post black", "blackened", "heavy psych")
EXCLUDE_TITLE = re.compile(
    r"^(soir[eé]e de soutien|blind[\s-]?test|masterclass|atelier|"
    r"conf[eé]rence|formation|concert annul[eé])\b", re.I
)


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join(re.findall(r"[a-z0-9]+",
                               value.encode("ascii", "ignore").decode()))


def genre_is_relevant(value):
    tokens = [normalize(x) for x in str(value).split(",")]
    return any(
        any(normalize(key) in token for key in STRICT_MUSIC)
        for token in tokens
    )


def safe_event_url(url, base):
    if not url:
        return None
    full = urllib.parse.urljoin(base, url).split("#")[0]
    parts = urllib.parse.urlsplit(full)
    origin = urllib.parse.urlsplit(base)
    if (parts.scheme == "https" and
        parts.netloc.lower() == origin.netloc.lower() and
        re.fullmatch(r"/events/[^/?#]+/?", parts.path)):
        return full
    return None


class MolotovParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading = None
        self.depth = 0
        self.fragments = []
        self.anchors = []
        self.current = {}
        self.rows = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self.anchors.append(a.get("href"))
            # Le lien officiel est souvent un <a> situé DANS le <h1>.
            if self.heading == "h1" and a.get("href"):
                self.heading_link = a["href"]
        if self.heading is not None:
            self.depth += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.heading = tag
            self.depth = 1
            self.fragments = []
            self.heading_link = self.anchors[-1] if self.anchors else None

    def handle_data(self, data):
        if self.heading is not None:
            self.fragments.append(data)

    def handle_endtag(self, tag):
        if self.heading is not None:
            self.depth -= 1
            if self.depth == 0:
                value = " ".join(" ".join(self.fragments).split())
                self.on_heading(self.heading, value, self.heading_link)
                self.heading = None
        if tag == "a" and self.anchors:
            self.anchors.pop()

    def on_heading(self, tag, value, href):
        if tag == "h2" and re.fullmatch(r"\d{1,2}", value):
            if self.current.get("name") and self.current.get("genres"):
                self.rows.append(self.current.copy())
            self.current = {"day": int(value)}
        elif tag == "h3" and self.current:
            v = value.casefold()
            if v in MONTHS:
                self.current["month"] = MONTHS[v]
            elif re.fullmatch(r"20\d{2}", v):
                self.current["year"] = int(v)
        elif tag == "h4" and self.current and "@" in value:
            match = TIME.search(value)
            self.current["venue_line"] = value
            if match:
                self.current["time"] = f"{int(match.group(1)):02d}:{match.group(2)}"
        elif tag == "h1" and self.current:
            self.current["name"] = value
            if href:
                self.current["event_link"] = href
        elif tag == "h2" and self.current.get("name"):
            self.current["genres"] = value
            self.rows.append(self.current.copy())
            self.current = {}


def molotov_candidates(page, source_url, venue, day):
    p = MolotovParser()
    p.feed(page)
    if p.current.get("name") and p.current.get("genres"):
        p.rows.append(p.current)
    candidates = []
    seen = set()
    for row in p.rows:
        name = row.get("name", "")
        genres = row.get("genres", "")
        if not name or not genre_is_relevant(genres) or EXCLUDE_TITLE.search(name):
            continue
        venue_line = normalize(row.get("venue_line", ""))
        # Le même calendrier couvre plusieurs salles (Molotov et Le Dodu).
        # Vérifier le nom EXACT du lieu demandé avant de créer une piste.
        venue_name = normalize(venue["name"])
        if venue_name not in venue_line:
            continue
        try:
            event_date = dt.date(row["year"], row["month"], row["day"]).isoformat()
        except (KeyError, ValueError, TypeError):
            continue
        if event_date < day:
            continue
        key = (event_date, normalize(name))
        if key in seen:
            continue
        seen.add(key)
        event_link = safe_event_url(row.get("event_link"), source_url)
        candidates.append({
            "candidateId": "molotov:" + event_date + ":" +
                           re.sub(r"\s+", "-", normalize(name))[:90],
            "source": "agenda_officiel_molotov_genre",
            "sourceUrl": event_link or source_url, "sourcePage": source_url,
            "date": event_date, "localTime": row.get("time"),
            "name": name, "leadArtist": name, "venue": venue["name"],
            "city": venue["city"], "department": venue.get("department"),
            "classification": [x.strip() for x in genres.split(",") if x.strip()],
            "genreToConfirm": False, "reviewRequired": True,
            "publicationAllowed": False,
            "sourceConfidence": "Source officielle Molotov, genre annoncé ; date/affiche à revérifier",
        })
    return candidates
