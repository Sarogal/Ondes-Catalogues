"""Read-only first-party list diagnostics: Rock n' Eat and Maison Bleue.

An agenda is a discovery lead, never an approved event. Rock n' Eat lacks
event-level genre badges and may show dates in an on-page month/year calendar;
it can only emit explicit review leads (genreToConfirm=True). Maison Bleue
shows a complete year and explicit event genre on its cards. Both need
individual independent verification before any map publication.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit

HOSTS = {
    "rockneat": ("www.rockneat.com", "/Programmation",
                 "Rock n' Eat", "Lyon"),
    "maisonbleue": ("www.lamaisonbleue-stbg.com", "/agenda/",
                   "La Maison Bleue", "Strasbourg"),
}
MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "aou": 8, "sep": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
METAL_LABELS = {
    "metal", "metalcore", "death metal", "black metal", "heavy metal",
    "hardcore", "punk", "punk rock", "stoner", "stoner rock", "doom",
}
NON_CONCERT = re.compile(
    r"\b(atelier|initiations?|masterclass|formation|annul[eé]|report[eé]|"
    r"cancelled|postponed|spectacle|comedie|cabaret)\b", re.I
)


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                               text.encode("ascii", "ignore").decode("ascii")))


class TextTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.tokens = []
        self.tag_stack = []
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden += 1
        self.tag_stack.append(tag)
    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "noscript") and self.hidden:
            self.hidden -= 1
        if self.tag_stack:
            self.tag_stack.pop()
    def handle_data(self, data):
        if self.hidden:
            return
        for line in data.splitlines():
            t=" ".join(line.split())
            if t:
                self.tokens.append((self.tag_stack[-1] if self.tag_stack else "", t))


def exact_page(url, kind):
    host, path, _, _ = HOSTS[kind]
    u = urlsplit(url)
    return (u.scheme == "https" and u.hostname == host and
            u.path == path and not u.username and not u.password
            and not u.query and not u.fragment and not u.port)


def lead(kind, source, date, title, genre, page, genre_unknown=False):
    city=HOSTS[kind][3]
    slug="-".join(norm(title).split())[:90]
    return {
        "candidateId":kind+":"+date.isoformat()+":"+slug,
        "source": "agenda_officiel_"+kind+"_review",
        "sourceUrl":page,
        "sourcePage":page,
        "date":date.isoformat(),
        "localTime":None,
        "name":title,
        "leadArtist":title.split("+")[0].strip() if "+" in title else title,
        "venue":source["name"],
        "city":city,
        "department":source["department"],
        "classification":[genre] if genre else [],
        "genreToConfirm":genre_unknown,
        "reviewBucket": "official_listing_requires_individual_confirmation",
        "publicationAllowed":False,
        "reviewRequired":True,
        "sourceConfidence":"Agenda officiel daté ; affiche et horaires à recouper individuellement. "
                           "Aucune approbation, aucune publication.",
    }


def maison_bleue(html, page, source, today, cap=25):
    if not exact_page(page,"maisonbleue") or (
        source.get("name"),source.get("city")) != (
            "La Maison Bleue","Strasbourg"):
        raise ValueError("La Maison Bleue: URL / identité de salle non conforme")
    p=TextTokens()
    p.feed(html)
    fields=[value for _,value in p.tokens]
    today=dt.date.fromisoformat(str(today))
    result={}
    # Exact consecutive [headline, full-date, genre] from venue's event cards.
    # Never infer a year from site copyright or the current date.
    date_re=re.compile(r"^(\d{1,2})\s+(jan|fev|mar|avr|mai|juin|juil|aou|sep|oct|nov|dec)[a-z]*\s+(20\d{2})$",re.I)
    for i in range(1,len(fields)-1):
        m=date_re.fullmatch(norm(fields[i]))
        if not m:
            continue
        try:
            date=dt.date(int(m[3]),MONTHS[m[2].lower()],int(m[1]))
        except ValueError:
            continue
        title=fields[i-1].strip()
        genre=norm(fields[i+1])
        if (date < today or genre not in METAL_LABELS or
                len(norm(title)) < 3 or len(title)>150 or
                NON_CONCERT.search(norm(title))):
            continue
        entry=lead("maisonbleue",source,date,title,fields[i+1],page)
        result[entry["candidateId"]]=entry
        if len(result)>=min(30,max(1,cap)):
            break
    return list(result.values())


def rockneat(html, page, source, today, cap=20):
    if not exact_page(page,"rockneat") or (
        source.get("name"),source.get("city")) != ("Rock n' Eat","Lyon"):
        raise ValueError("Rock n' Eat: URL / identité de salle non conforme")
    parser=TextTokens()
    parser.feed(html)
    fields=parser.tokens
    today=dt.date.fromisoformat(str(today))
    # A single anchored full year/month segment is required, and only
    # DAY + HHhMM + H1 title after that segment counts. A duplicate
    # headline in the slider above the program does NOT become an event.
    anchors=[
        i for i in range(len(fields)-2)
        if norm(fields[i][1])=="programmation"
        and norm(fields[i+1][1]) in ("novembre","decembre","janvier",
          "fevrier","mars","avril","mai","juin","juillet","aout","septembre","octobre")
        and re.fullmatch(r"20\d\d",fields[i+2][1])
    ]
    if len(anchors)!=1:
        return []
    i=anchors[0]
    month={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}[norm(fields[i+1][1])]
    year=int(fields[i+2][1])
    result={}
    for k in range(i+3,len(fields)-2):
        kind,day_text=fields[k]
        if not re.fullmatch(r"\d{1,2}",day_text):
            continue
        if not re.fullmatch(r"[0-2]?\d[Hh][0-5]\d",fields[k+1][1]):
            continue
        headline_tag,title=fields[k+2]
        if headline_tag!="h1" or not (3<=len(norm(title))<=150):
            continue
        # No per-event metal tag exists. Restrict leads to explicitly
        # named multi-artist bills and keep genre uncertain.
        if "+" not in title or NON_CONCERT.search(norm(title)):
            continue
        try:
            date=dt.date(year,month,int(day_text))
        except ValueError:
            continue
        if date<today:
            continue
        entry=lead("rockneat",source,date,title.strip(),None,page,True)
        result[entry["candidateId"]]=entry
        if len(result)>=min(25,max(1,cap)):
            break
    return list(result.values())
