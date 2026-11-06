"""La Laiterie / Artefact: bounded official event details, discovery only.

Never treat door opening as concert start. The venue's large paginated
calendar is a link index; only matching, dated first-party event details
produce leads. Geography remains the existing approved catalogue record.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOST = "www.artefact.org"
AGENDA = "https://www.artefact.org/la-laiterie/programmation/"
DETAIL = re.compile(r"/la-laiterie/evenements/([a-z0-9-]+)/")
PAGE = re.compile(r"/la-laiterie/programmation/page/([2-9]|1[0-2])/")
MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
          "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
DATE = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
GENRE = re.compile(
    r"\b(?:metal|punk|hardcore|rock|stoner|shoegaze|mathcore|grunge|"
    r"noise|sludge|doom|thrash|post-punk|post-hardcore|deathcore|"
    r"blackgaze|indie rock|hard rock)\b", re.I)
CANCEL = re.compile(r"\b(?:annule|annulee|reporte|reportee|deplace|deplacee|"
                    r"cancelled|canceled|postponed)\b")


def fold(s):
    return unicodedata.normalize("NFKD", unescape(str(s)).casefold()).encode(
        "ascii", "ignore").decode("ascii")


def valid_detail(url):
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != HOST or u.query or u.fragment
            or u.username or u.password or u.port):
        return None
    m = DETAIL.fullmatch(u.path)
    return m[1] if m else None


class _Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.visible = []
        self.headings = []
        self.hide = 0
        self.in_heading = None
        self.heading_parts = []
        self.main_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "main":
            self.main_depth += 1
        if tag in ("head", "script", "style", "nav", "footer"):
            self.hide += 1
        if tag == "a":
            for k,v in attrs:
                if k.lower() == "href" and v:
                    self.links.append(v)
        if tag in ("h1", "h2") and self.main_depth and not self.hide:
            self.in_heading = tag
            self.heading_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("h1", "h2") and self.in_heading == tag:
            self.headings.append((tag, " ".join(self.heading_parts).strip(), len(self.visible)))
            self.in_heading = None
            self.heading_parts = []
        if tag in ("head", "script", "style", "nav", "footer") and self.hide:
            self.hide -= 1
        if tag == "main" and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data):
        if self.hide or not self.main_depth:
            return
        t = " ".join(data.split())
        if t:
            self.visible.append(t)
            if self.in_heading:
                self.heading_parts.append(t)


def links(html, page_url):
    if not page_url.startswith(AGENDA):
        raise ValueError("La Laiterie official agenda required")
    p = _Extract()
    p.feed(html)
    return sorted({u for raw in p.links
                   if (u := urljoin(page_url, raw)) and valid_detail(u)})


def max_agenda_page(html, page_url):
    p = _Extract()
    p.feed(html)
    values = [1]
    for raw in p.links:
        u = urlsplit(urljoin(page_url, raw))
        if u.scheme == "https" and u.hostname == HOST:
            m = PAGE.fullmatch(u.path)
            if m:
                values.append(int(m[1]))
    return max(values)


def details(html, url, source, day):
    if not valid_detail(url):
        raise ValueError("Untrusted official detail path")
    if source.get("name") != "La Laiterie" or source.get("city") != "Strasbourg":
        raise ValueError("Unexpected venue")
    scan_date = dt.date.fromisoformat(day)
    p = _Extract()
    p.feed(html)
    if not p.visible or not p.headings:
        raise ValueError("No individual concert content")
    body = " ".join(p.visible)
    # A named venue and a single year-qualified full date must exist in the
    # event section before Genre, not merely in tour recommendations.
    marker = next((i for i,t in enumerate(p.visible) if fold(t) == "genre"), None)
    if marker is None:
        raise ValueError("No first-party event genre")
    intro = " ".join(p.visible[:marker])
    dates = set()
    for d,month,y in DATE.findall(fold(intro)):
        try:
            dates.add(dt.date(int(y), MONTHS[month], int(d)))
        except ValueError:
            raise ValueError("Invalid year-qualified event date") from None
    if len(dates) != 1:
        raise ValueError("Ambiguous or absent full event date")
    date = next(iter(dates))
    if date < scan_date or date > scan_date + dt.timedelta(days=365):
        raise ValueError("Out of calendar horizon")
    if "laiterie, grande salle" not in fold(intro) and "laiterie, petite salle" not in fold(intro):
        raise ValueError("Event not hosted in La Laiterie")
    title = next((s for k,s,n in p.headings if k == "h1" and n < marker), "")
    support = next((s for k,s,n in p.headings
                    if k == "h2" and n < marker and fold(s).startswith("+")), "")
    if not 2 <= len(title) <= 140 or CANCEL.search(fold(intro)):
        raise ValueError("Cancelled, moved, or unnamed concert")
    # Genre on the detail is a single tagged field, never a band biography.
    tagged = []
    for token in p.visible[marker+1:marker+5]:
        if token.lstrip().startswith("#"):
            tagged.append(token.lstrip("# ").strip())
        elif tagged:
            break
    if len(tagged) != 1 or not GENRE.search(fold(tagged[0])):
        raise ValueError("No explicit rock or metal genre tag")
    name = title if not support else title + " " + support
    name = " ".join(name.replace(" + ", " + ").split())
    if len(name) > 200:
        raise ValueError("Unreasonably long concert title")
    # No times are extracted. The individual pages label them as door times.
    return {
        "candidateId": f"laiterie:{date.isoformat()}:{valid_detail(url)}",
        "name": name, "leadArtist": title, "date": date.isoformat(),
        "venue": "La Laiterie", "city": "Strasbourg", "department": "67",
        "classification": [tagged[0]],
        "source": "agenda_officiel_laiterie_detail_review",
        "sourcePage": source["url"], "sourceUrl": url,
        "sourceConfidence": "Détail officiel Artefact, date complète, salle et genre ; affiche individuelle à approuver séparément. Heures des portes exclues.",
        "officialDetailFound": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
    }
