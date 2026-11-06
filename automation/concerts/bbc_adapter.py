"""Big Band Café, Hérouville-Saint-Clair — official review leads ONLY.

The venue's WordPress listing has full dated cards and each card links to
an official one-act detail page. Artist biographies contain many irrelevant
historic album years: the concert date is accepted ONLY from the explicit
H2 ticket header (e.g. 'ven. 5 février 2027 - 20:00'). That displayed 20:00
is not labelled a musical start, so the candidate's localTime is always None.

No approvals and no JSON publication are performed by this module.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://bigbandcafe.com/concerts/"
HOST = "bigbandcafe.com"
PATH = re.compile(r"/([a-z0-9]+(?:-[a-z0-9]+)*)/")
STATIC_SLUGS = {
    "concerts", "agenda", "archives", "le-bbc", "contact", "faq",
    "accessibilite", "formations", "scene-regionale", "2step",
    "partenaires", "politique-de-confidentialite", "mentions-legales",
    "locaux-de-repetition", "actions-culturelles", "photos-du-bbc",
    "bourse-aux-billets", "espace-pro-presse-technique",
}
MONTHS = {
    "janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,
    "juin":6,"juillet":7,"aout":8,"septembre":9,
    "octobre":10,"novembre":11,"decembre":12,
}
MONTH_RE = "|".join(MONTHS)
DATE_RE = re.compile(r"\b([0-3]?\d)\s+(" + MONTH_RE +
                     r")\s+(20\d{2})\s*[-–]\s*(\d\d?):(\d{2})\b")
GENRE_RE = re.compile(
    r"\b(?:hard\s+rock|metal\s+alternatif|heavy\s+metal|"
    r"death\s+metal|black\s+metal|punk(?:\s+rock)?|hardcore|"
    r"stoner|doom|sludge|garage\s+rock|garage|noise|post[- ]rock|"
    r"rock|metal)\b"
)
EXCLUDE = re.compile(
    r"\b(?:festival|atelier|conference|rencontre|exposition|"
    r"seance|comedie|theatre|visite|masterclass|"
    r"annul(?:e|ation)|reporte)\b")
SKIP = {"script","style","noscript","nav","footer","svg","aside"}


def fold(value):
    return unicodedata.normalize(
        "NFKD", unescape(str(value or "")).casefold()
    ).encode("ascii","ignore").decode("ascii")


def allowed_agenda(url):
    p = urlsplit(url)
    return (p.scheme == "https" and p.hostname == HOST and
            p.path == "/concerts/" and not (
                p.port or p.username or p.password or p.query or p.fragment))


def event_url(value, base=AGENDA):
    u = urljoin(base, str(value or ""))
    parsed = urlsplit(u)
    match = PATH.fullmatch(parsed.path)
    if not (parsed.scheme == "https" and parsed.hostname == HOST
            and match and match.group(1) not in STATIC_SLUGS
            and not (parsed.port or parsed.username or parsed.password
                     or parsed.query or parsed.fragment)):
        return None
    return u


class Page(HTMLParser):
    """Read the first content <section> and its headings, ignoring menus."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section_depth = 0
        self.skip_depth = 0
        self.links = []
        self.headings = {1:[], 2:[]}
        self.heading = 0
        self.body = []
        self.in_first_section = False
        self.first_section_finished = False
        self.seen_h1 = False

    def handle_starttag(self, tag, attrs):
        tag=tag.lower()
        if tag in SKIP:
            self.skip_depth += 1
        if tag=="section" and not self.first_section_finished and not self.skip_depth:
            self.section_depth += 1
            self.in_first_section = True
        if not self.in_first_section or self.skip_depth:
            return
        if tag in ("h1","h2"):
            level=int(tag[1:])
            self.heading = level
            if level == 1:
                self.seen_h1 = True
        if tag=="a":
            u=event_url(dict(attrs).get("href"))
            if u and u not in self.links:
                self.links.append(u)

    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag in ("h1","h2") and self.heading==int(tag[1:]):
            self.heading=0
        if tag=="section" and self.in_first_section:
            self.section_depth-=1
            if self.section_depth<=0:
                self.in_first_section=False
                self.first_section_finished=True
        if tag in SKIP and self.skip_depth:
            self.skip_depth-=1

    def handle_data(self, data):
        if not self.in_first_section or self.skip_depth:
            return
        val=" ".join(data.split())
        if not val:
            return
        self.body.append(val)
        if self.heading:
            self.headings[self.heading].append(val)


def official_links(markup, source_url=AGENDA):
    if not allowed_agenda(source_url):
        raise ValueError("Big Band Café listing URL outside allowlist")
    parser=Page()
    parser.feed(markup)
    if not parser.in_first_section and not parser.first_section_finished:
        raise ValueError("Big Band Café official list structure absent")
    return parser.links


def selected_urls(urls, known, today, limit=8):
    quota=max(1,min(8,int(limit)))
    clean=sorted(set(url for url in urls if event_url(url)==url))
    unseen=[u for u in clean if ("officialUrl",u) not in known]
    existing=[u for u in clean if ("officialUrl",u) in known]
    def rotate(values,n):
        if not values or n<=0:
            return []
        start=dt.date.fromisoformat(today).toordinal()%len(values)
        return [values[(start+i)%len(values)] for i in range(min(n,len(values)))]
    first=rotate(unseen,quota)
    return first+rotate(existing,quota-len(first))


def candidate(markup, url, source, today):
    if (event_url(url)!=url or source.get("name")!="Big Band Café"
            or source.get("city")!="Hérouville-Saint-Clair"
            or source.get("department")!="14"
            or source.get("url")!=AGENDA):
        raise ValueError("Untrusted BBC page URL or declared venue")
    page=Page()
    page.feed(markup)
    if not page.first_section_finished:
        raise ValueError("No BBC detail section")
    if len(page.headings[1])!=1 or len(page.headings[2])!=1:
        raise ValueError("Unexpected event title or ticket-date heading")
    title=" ".join(page.headings[1][0].split()).strip()
    date_heading=fold(page.headings[2][0])
    if not (3<=len(title)<=150) or EXCLUDE.search(fold(title)):
        raise ValueError("Nonconcert or ambiguous headline")
    date_match=DATE_RE.search(date_heading)
    if not date_match:
        raise ValueError("No complete official year and printed time in H2")
    d,m,y,h,mins=date_match.groups()
    try:
        date=dt.date(int(y),MONTHS[m],int(d))
    except ValueError as e:
        raise ValueError("Invalid date in official H2") from e
    current=dt.date.fromisoformat(today)
    if not current<=date<=current+dt.timedelta(days=365):
        raise ValueError("Outside future one-year window")
    # The explicit genre must be in the event's written description,
    # not in global navigation or another card's recommended event.
    desc=fold(" ".join(page.body[:180]))
    found=GENRE_RE.search(desc)
    if not found:
        raise ValueError("Musical genre unsupported or unproven")
    if EXCLUDE.search(fold(title+" "+date_heading)):
        raise ValueError("Cancelled, postponed, festival or workshop")
    if len(re.findall("[a-z]",fold(title.split(" + ")[0])))<3:
        raise ValueError("Unidentified performer")
    slug=PATH.fullmatch(urlsplit(url).path).group(1)
    return {
        "candidateId":f"bbc:{date.isoformat()}:{slug}",
        "name":title,
        "leadArtist":re.split(r"\s+\+\s+",title,1)[0],
        "date":date.isoformat(),
        "venue":"Big Band Café",
        "city":"Hérouville-Saint-Clair",
        "department":"14",
        "classification":[found.group(0).title()],
        "genreToConfirm":True,
        "source":"bbc_official_detail_review",
        "sourcePage":AGENDA,
        "sourceUrl":url,
        "officialDetailFound":True,
        "dateEvidence":"first_party_detail_ticket_h2_full_year",
        "announcedClock":f"{int(h):02d}:{int(mins):02d}",
        "localTime":None,
        "timeMeaning":"displayed_clock_unqualified_not_musical_start",
        "sourceConfidence":(
            "Fiche première main Big Band Café avec affiche, date complète et "
            "genre décrit; le 20h de l'en-tête n'est pas attesté comme début "
            "du concert. Contrôler statut et artistes avant approbation."
        ),
        "reviewRequired":True,"publicationAllowed":False,
    }
