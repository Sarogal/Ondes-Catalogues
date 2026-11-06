"""Billetweb discovery for Le Brin de Zinc, Barberaz: leads only, never approval.

The venue's own home page links to Billetweb, but its public agenda cannot be
reliably parsed. The ticketing overview is treated as a SECONDARY source:
it supplies dated candidates to review, not independent official proof.
No event links are followed and no catalogue is ever updated here.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit

TICKETING = "https://www.billetweb.fr/multi_event.php?multi=11236"
MONTHS = {name: i for i, name in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
WEEKDAYS = "Mon Tue Wed Thu Fri Sat Sun".split()
DATE = re.compile(
    r"\b(?P<dow>Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\s+"
    r"(?:from|at)\s+(?P<hour>\d{1,2}):(?P<minute>[0-5]\d)\s+"
    r"(?P<period>AM|PM)\b", re.I)
MORE_INFO = re.compile(r"\bMore info\b(?!rmation)", re.I)
CUT = re.compile(r"\b(?:Learn more|Hide description|More information)\b", re.I)
LOCATION = re.compile(
    r"^\s*(?:to\s+\d{1,2}:[0-5]\d\s+(?:AM|PM)\s+)?Le Brin de Zinc,\s*Route de la Peysse,\s*Barberaz,\s*France\b", re.I)
GENRE = re.compile(
    r"\b(?:metal|punk|hardcore|doom|stoner|sludge|grind|deathcore|"
    r"thrash|heavy psych|post metal|power metal|hard rock)\b", re.I)
REJECT = re.compile(
    r"\b(?:festival|atelier|masterclass|abonnement|adhesion|"
    r"don|t shirt|boutique|cours|dj set|annule|annulee|reporte)\b", re.I)


def flat(value):
    return unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore").decode("ascii").lower()


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def candidates(page, page_url, source, today, limit=45):
    """Conservatively parse visible ticket cards; skip incomplete/uncertain ones.

    Never infer a year, a genre, a location, a ticket availability, or a
    concert start time from the generic venue opening hours.
    """
    url = urlsplit(page_url)
    if (url.scheme != "https" or url.hostname != "www.billetweb.fr"
            or url.path != "/multi_event.php" or url.query != "multi=11236"
            or url.username or url.password or url.fragment):
        raise ValueError("Unexpected ticketing origin")
    if (source.get("name") != "Le Brin de Zinc"
            or source.get("city") != "Barberaz"
            or source.get("department") != "73"):
        raise ValueError("Unexpected venue identity")
    visible = VisibleText()
    visible.feed(page)
    text = " ".join(visible.parts)
    if (not re.search(r"<(?:title|h1|header)\b[^>]*>[^<]{0,160}Brin de Zinc", page, re.I)
            or "Brin de Zinc" not in text):
        raise ValueError("Ticketing page does not identify the venue")
    today_date = dt.date.fromisoformat(str(today))
    leads = []
    seen = set()
    for match in DATE.finditer(text):
        if len(leads) >= limit:
            break
        preceding = text[:match.start()]
        infos = list(MORE_INFO.finditer(preceding[max(0, len(preceding)-260):]))
        if not infos:
            continue
        info_pos = max(0, len(preceding)-260) + infos[-1].start()
        if len(preceding) - (info_pos + len("More info")) > 24:
            continue
        title_prefix = preceding[:info_pos]
        cuts = list(CUT.finditer(title_prefix[max(0, len(title_prefix)-350):]))
        cut_pos = (max(0, len(title_prefix)-350) + cuts[-1].end()) if cuts else 0
        title = " ".join(title_prefix[cut_pos:].split())
        if not 5 <= len(title) <= 190:
            continue
        following = text[match.end():match.end()+145]
        if not LOCATION.match(following):
            continue
        try:
            parsed_date = dt.date(int(match["year"]), MONTHS[match["month"].title()],
                                  int(match["day"]))
        except ValueError:
            continue
        if parsed_date < today_date or parsed_date.weekday() != WEEKDAYS.index(match["dow"].title()):
            continue
        hour = int(match["hour"])
        if not 1 <= hour <= 12:
            continue
        hour = hour % 12 + (12 if match["period"].upper() == "PM" else 0)
        genre_terms = re.findall(r"\(([^()]*)\)", title)
        if not genre_terms or not any(GENRE.search(flat(x).replace("-", " ")) for x in genre_terms):
            continue
        if REJECT.search(flat(title).replace("-", " ")):
            continue
        sold_out = bool(re.match(r"(?i)^\s*(?:complet|sold out)\b", title))
        artist = re.sub(r"(?i)^\s*(?:complet|sold out)\s*[•:\-]*\s*", "", title)
        artist = artist.split("(", 1)[0]
        artist = re.split(r"\s+(?:x|X|\+)\s+", artist, maxsplit=1)[0].strip()
        if not artist or len(artist) > 110:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", flat(title)).strip("-")[:85]
        identifier = f"brin-de-zinc:{parsed_date.isoformat()}:{slug}"
        if identifier in seen:
            continue
        seen.add(identifier)
        leads.append({
            "candidateId": identifier,
            "source": "billetterie_brin_de_zinc_a_recouper",
            "sourceUrl": TICKETING, "sourcePage": source["url"],
            "name": title, "leadArtist": artist,
            "date": parsed_date.isoformat(), "localTime": f"{hour:02d}:{match['minute']}",
            "venue": "Le Brin de Zinc", "city": "Barberaz", "department": "73",
            "classification": genre_terms, "genreToConfirm": True,
            "ticketStatus": "sold_out" if sold_out else "not_verified",
            "thirdPartyOnly": True, "reviewRequired": True,
            "publicationAllowed": False,
            "sourceConfidence": "Billetterie liée à la salle ; date et genre à recouper avec l'annonce officielle"
        })
    return leads
