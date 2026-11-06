"""Collecte Joker's Pub : date avec année sur la page officielle, genre sur fiche.

Toutes les entrées sont des PISTES non publiables. Les DJ sets et animations sont
exclus ; les affiches non confirmées par le détail restent genre inconnu.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
import urllib.parse

MONTH = {"JAN":1,"JANV":1,"FEV":2,"FÉV":2,"MAR":3,"AVR":4,"MAI":5,
         "JUIN":6,"JUIL":7,"AOU":8,"AOÛ":8,"SEP":9,"SEPT":9,
         "OCT":10,"NOV":11,"DEC":12,"DÉC":12}
DATE = re.compile(
    r"\b(?:LUN|MAR|MER|JEU|VEN|SAM|DIM)\s+(\d{1,2})\s+"
    r"(JANV?|F[EÉ]V|MAR|AVR|MAI|JUIN|JUIL|AO[UÛ]|SEPT?|OCT|NOV|D[EÉ]C)"
    r"\s+(20\d{2})\s*(\d{1,2})[hH](\d\d)", re.I)
DETAIL = re.compile(r"^/jokers-concert-programmation-[^/?#]+\.html$", re.I)
NON_CONCERT = re.compile(
    r"\b(dj.set|deaf.test|blind.test|retransmission|jam.session|"
    r"conference|atelier|formation|quiz|apero.impro|masterclass|"
    r"projection|stand.up|theatre|match.sportif)\b", re.I)
GENRE = re.compile(
    r"\b(metal|metalcore|deathcore|punk|hardcore|grind|thrash|doom|"
    r"stoner|sludge|black metal|heavy metal)\b", re.I)


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+",text.encode("ascii","ignore").decode()))


class Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.li_depth = 0
        self.p_depth = 0
        self.p_parts = []
        self.date_depth = 0
        self.date_parts = []
        self.paragraphs = []
        self.urls = []
        self.cancelled = False
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li":
            if self.li_depth == 0:
                self.paragraphs, self.urls, self.cancelled = [], [], False
            self.li_depth += 1
        if not self.li_depth:
            return
        # In production the homepage slider uses <div class="slide__date">
        # with a nested <span> for the time, not a <p> for the date.
        if self.date_depth:
            if tag not in ("br", "img", "input", "meta", "link", "hr"):
                self.date_depth += 1
        elif tag == "div" and "slide__date" in (attrs.get("class") or "").split():
            self.date_depth, self.date_parts = 1, []
        if tag == "p":
            if self.p_depth == 0:
                self.p_parts = []
            self.p_depth += 1
        if tag == "a" and attrs.get("href"):
            self.urls.append(attrs["href"])
        if tag in ("img", "span"):
            hint = " ".join(str(attrs.get(x,"")) for x in ("alt","title","class"))
            if "annul" in normalize(hint):
                self.cancelled = True

    def handle_data(self, text):
        if self.li_depth and self.p_depth:
            self.p_parts.append(text)
        if self.li_depth and self.date_depth:
            self.date_parts.append(text)

    def handle_endtag(self, tag):
        if self.date_depth and tag not in ("br", "img", "input", "meta", "link", "hr"):
            self.date_depth -= 1
            if self.date_depth == 0:
                date_value = " ".join(" ".join(self.date_parts).split())
                if date_value:
                    self.paragraphs.append(date_value)
                self.date_parts = []
        if tag == "p" and self.p_depth:
            self.p_depth -= 1
            if self.p_depth == 0:
                value = " ".join(" ".join(self.p_parts).split())
                if value:
                    self.paragraphs.append(value)
        elif tag == "li" and self.li_depth:
            self.li_depth -= 1
            if self.li_depth == 0:
                self.rows.append((self.paragraphs[:],self.urls[:],self.cancelled))


def safe_detail(hrefs, base):
    root = urllib.parse.urlsplit(base)
    for href in hrefs:
        url = urllib.parse.urljoin(base,href).split("#",1)[0]
        p = urllib.parse.urlsplit(url)
        if (p.scheme=="https" and p.hostname == root.hostname
            and DETAIL.fullmatch(p.path) and not p.query):
            return url
    return None


def listing_candidates(page, source_url, venue, today):
    parsed = Listing()
    parsed.feed(page)
    result = []
    seen = set()
    for paras,hrefs,cancelled in parsed.rows:
        for i,line in enumerate(paras):
            match = DATE.search(line)
            if not match or not i:
                continue
            title = paras[i-1]
            if len(title)>180 or len(title)<3 or NON_CONCERT.search(normalize(title)):
                break
            try:
                month = MONTH[match.group(2).upper()]
                date = dt.date(int(match.group(3)),month,int(match.group(1)))
                # Avoid accepting an inconsistent year or impossible clock
                # in an official homepage banner.
                weekday = ("LUN","MAR","MER","JEU","VEN","SAM","DIM").index(
                    line[match.start():match.start()+3].upper())
                if date.weekday() != weekday or int(match.group(4)) > 23:
                    break
                day = date.isoformat()
            except (ValueError,KeyError):
                break
            if day < today:
                break
            detail = safe_detail(hrefs,source_url)
            if not detail:
                break
            key = (day,normalize(title))
            if key in seen:
                break
            seen.add(key)
            result.append({
                "candidateId": "joker:"+day+":"+
                    re.sub(r"[^a-z0-9]+","-",normalize(title))[:65],
                "source":"agenda_officiel_jokers_date",
                "sourceUrl":detail,"sourcePage":source_url,
                "date":day,"localTime":f"{int(match.group(4)):02d}:{match.group(5)}",
                "name":title,"leadArtist":title,
                "venue":venue["name"],"city":venue["city"],
                "department":venue["department"],
                "genreToConfirm":True,
                "venueToConfirm":True,
                "publicationAllowed":False,"reviewRequired":True,
                "cancellationNotice":cancelled,
                "sourceConfidence":"Date issue de la page officielle; genre et salle à confirmer sur fiche",
            })
            break
    return result


class Headings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = None
        self.depth = 0
        self.parts = []
        self.headings = {}
    def handle_starttag(self,tag,attrs):
        if self.capture is not None:
            self.depth+=1
        elif tag in ("h1","h2"):
            self.capture=tag
            self.depth=1
            self.parts=[]
    def handle_data(self,data):
        if self.capture:
            self.parts.append(data)
    def handle_endtag(self,tag):
        if self.capture:
            self.depth-=1
            if self.depth==0:
                self.headings.setdefault(self.capture,[]).append(
                    " ".join(" ".join(self.parts).split()))
                self.capture=None


def with_details(candidate, html_page):
    """Ne renseigne le genre que si le titre de la fiche correspond à celui du jour."""
    out=dict(candidate)
    headings=Headings()
    headings.feed(html_page)
    h1=headings.headings.get("h1",[])
    h2=headings.headings.get("h2",[])
    # An official programme title may contain multiple artists, each with
    # a separate H1/H2 block. Require every artist name, in order; a single
    # matching H1 is not evidence for the entire bill.
    expected=[normalize(part) for part in re.split(r"\s+\+\s+",out["name"])]
    actual=[normalize(item) for item in h1]
    if not actual or actual != expected:
        out["detailStatus"]="mismatch_or_missing_title"
        return out
    out["detailStatus"]="title_matched"
    if len(h2)==len(h1) and all(GENRE.search(normalize(label)) for label in h2):
        out["classification"]=h2[:]
        out["genreToConfirm"]=False
    if any("festival" in normalize(label) for label in h2):
        out["festivalContext"]=True
    if any("joker s cafe" in normalize(label) for label in h2):
        out["venueToConfirm"]=True
    return out


class AllText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
    def handle_data(self, data):
        self.parts.append(data)


def diagnose_layout(page):
    """Comptes structurels seulement, aucune donnée privée ni page intégrale."""
    listing=Listing()
    listing.feed(page)
    text=AllText()
    text.feed(page)
    joined=" ".join(text.parts)
    return {
        "htmlLength":len(page),
        "listItems":len(listing.rows),
        "listItemsWithDates":sum(
            any(DATE.search(part) for part in paras)
            for paras,links,cancelled in listing.rows
        ),
        "datesInAllVisibleText":len(DATE.findall(joined)),
        "officialDetailLinks":len(re.findall(
            r"jokers-concert-programmation-[^\"' >]+\.html",page,re.I
        )),
    }
