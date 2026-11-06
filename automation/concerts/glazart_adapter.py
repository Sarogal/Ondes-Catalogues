"""Glazart first-party single-event discovery only — NEVER auto-publish.

The official agenda is a directory of exact same-domain event URLs. Each
event is kept only when its official detail page independently confirms the
date embedded in that URL, and its HTML title identifies an actual concert.
A shortened page headline is NOT evidence of the complete concert lineup.
If body prose names more acts they are review hints, not approved artists.
No genre, start time, ticket status or artist is inferred for publication.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOST = "www.glazart.com"
AGENDA = "/agenda-concerts/portfolio-category/concert/"
DETAIL = re.compile(r"/(?P<dd>\d{2})-(?P<mm>\d{2})-(?P<yy>2[0-9])-concert-[a-z0-9-]+/",re.I)
FRENCH_MONTHS = {
    "janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
    "juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,
    "decembre":12,
}
DATE_LONG = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
DATE_SHORT = re.compile(r"(?<!\d)([0-3]?\d)[./]([01]?\d)[./](2\d)(?!\d)")
CANCEL = re.compile(r"\b(annulee?|annulation|reporte[e]?|reportee|"
                    r"cancelled|canceled|postponed)\b")
BODY_LINEUP = re.compile(
    r"(?P<acts>[\wÀ-ÿ'’ .,-]{10,140})\s+(?:a|à)\s+Paris\s+le\s+"
    r"(?:[0-3]?\d)\s+(?:janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s+20\d\d\s+au\s+Glazart", re.I)
BULLET_ACT = re.compile(r"(?:□|■|▪|•)\s*([A-Z0-9][A-Z0-9 '&’.-]{2,65})\s*"
                        r"\(\s*(?:slam|death|black|metal|hardcore|punk)[^)]{0,30}\)",re.I)


def normalize(s):
    s=unicodedata.normalize("NFKD",str(s or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                               s.encode("ascii","ignore").decode("ascii")))


def safe_listing_url(url):
    u=urlsplit(url)
    return (u.scheme=="https" and u.hostname==HOST and
            u.path==AGENDA and not u.username and not u.password
            and not u.port and not u.query and not u.fragment)


def event_date(url):
    u=urlsplit(url)
    if (u.scheme!="https" or u.hostname!=HOST or u.username or
        u.password or u.port or u.query or u.fragment):
        return None
    m=DETAIL.fullmatch(u.path)
    if m is None:
        return None
    try:
        return dt.date(2000+int(m["yy"]),int(m["mm"]),int(m["dd"]))
    except ValueError:
        return None


class Extract(HTMLParser):
    """Only collect public markup; avoid scripts, menu noise, external links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs=[]
        self.depth=0
        self.suppressed=0
        self.title=[]
        self.content=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.suppressed+=1
        if tag=="title":
            self.depth+=1
        if tag=="a" and not self.suppressed:
            href=dict(attrs).get("href")
            if href:
                self.hrefs.append(href)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg") and self.suppressed:
            self.suppressed-=1
        if tag=="title" and self.depth:
            self.depth-=1
    def handle_data(self,data):
        if self.suppressed:
            return
        content=" ".join(data.split()).strip()
        if not content:
            return
        if self.depth:
            self.title.append(content)
        else:
            self.content.append(content)


def detail_links(html, listing_url, max_links=80):
    if not safe_listing_url(listing_url):
        raise ValueError("Not Glazart's exact public concert calendar")
    page=Extract()
    page.feed(html)
    links=[]
    seen=set()
    for item in page.hrefs:
        link=urljoin(listing_url,item)
        if event_date(link) is not None and link not in seen:
            links.append(link)
            seen.add(link)
            if len(links)>=max(1,min(100,max_links)):
                break
    return links


def confirmed_page_date(text, date):
    """Require the exact event date within first-party page, not only in URL."""
    normalized=normalize(text)
    found=[]
    for m in DATE_LONG.finditer(normalized):
        try:
            found.append(dt.date(int(m[3]),FRENCH_MONTHS[m[2]],int(m[1])))
        except ValueError:
            continue
    for m in DATE_SHORT.finditer(text):
        try:
            found.append(dt.date(2000+int(m[3]),int(m[2]),int(m[1])))
        except ValueError:
            continue
    return date in found


def artist_hints_from_body(text, headline):
    """Exact first-party explicit bill lines; suggestions never approved."""
    suggestions=[]
    m=BODY_LINEUP.search(text)
    if m:
        parts=re.split(r"\s*(?:,|\bet\b)\s*",m["acts"],flags=re.I)
        if 2<=len(parts)<=8 and all(2<=len(part.strip())<=65 for part in parts):
            suggestions=[p.strip() for p in parts]
    bullet=[m.group(1).strip() for m in BULLET_ACT.finditer(text)]
    if len(bullet)>=2:
        suggestions=bullet
    seen=set()
    unique=[]
    for name in suggestions:
        clean=normalize(name)
        if clean not in seen and clean and len(clean)<90:
            seen.add(clean)
            unique.append(name)
    return unique[:12]


def detail_candidate(html,url,source,today):
    date=event_date(url)
    if date is None or date<dt.date.fromisoformat(str(today)):
        raise ValueError("Invalid, off-domain, or past Glazart event")
    if (source.get("name"),source.get("city"))!=("Glazart","Paris") or (
        not safe_listing_url(source.get("url",""))):
        raise ValueError("Glazart source identity is not verified")
    p=Extract()
    p.feed(html)
    heading=" ".join(p.title).strip()
    # WordPress <title> is a dated, event-specific concert title. Do not
    # scrape an arbitrary band name from a generic navigation or artist bio.
    m=re.match(
        r"^\s*(\d{1,2})[./](\d{1,2})[./](2\d)\s*[–—-]\s*"
        r"Concert\s*:\s*(.{2,190}?)\s*(?:→|\||-|$)\s*GLAZART\b",
        heading,re.I)
    if not m:
        raise ValueError("Explicit dated concert page title missing")
    if (int(m[1]),int(m[2]),int(m[3]))!=(
         date.day,date.month,date.year%100):
        raise ValueError("Date in page title disagrees with detail URL")
    # Page must contain an independent date (short or long) in actual body,
    # NOT just one in page <title>; reject pages with only navigation.
    raw=" ".join(p.content)
    if not confirmed_page_date(raw,date):
        raise ValueError("Event detail has no matching dated evidence")
    title=m[4].strip()
    first=" ".join(p.content[:45])
    if (not 3<=len(normalize(title))<=180 or
        CANCEL.search(normalize(title)) or CANCEL.search(normalize(first[:350]))):
        raise ValueError("Canceled or unidentifiable concert")
    # 'Guest' in a shortened headline is not a real artist. Do not fabricate
    # complete lineups; first-party detailed listing may contain other names.
    hints=artist_hints_from_body(raw[:9000],title)
    abbreviated=("guest" in normalize(title) or "invite" in normalize(title)
                 or "x" in title.split())
    candidate={
        "candidateId":"glazart:"+date.isoformat()+":"+
                       urlsplit(url).path.strip("/"),
        "source":"agenda_officiel_glazart_detail",
        "sourceUrl":url,
        "sourcePage":source["url"],
        "date":date.isoformat(),
        "localTime":None,
        "name":title,
        "leadArtist":re.split(r"\s+\+\s+|\s+x\s+",title,1,flags=re.I)[0].strip(),
        "venue":"Glazart",
        "city":"Paris",
        "department":"75",
        # Genre in bios does not qualify as a formal genre tag on this site;
        # even the words Hardcore/Death are NOT publish approval.
        "classification":[],
        "genreToConfirm":True,
        "lineupToConfirm":True,
        "abbreviatedHeadline":abbreviated,
        "artistNamesToVerify":hints,
        "publicationAllowed":False,
        "reviewRequired":True,
        "sourceConfidence":"Date de concert confirmée par titre ET corps "
             "de la page officielle ; programmation, genre, annulation "
             "et heure à recouper avant publication."
    }
    return candidate
