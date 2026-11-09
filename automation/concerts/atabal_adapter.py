"""Atabal Biarritz: bounded FIRST PARTY live concert discovery, NEVER publishes.

The agenda is a simple WordPress link index with date in individual /concerts/
slug. An individual page must confirm this date, its bill and explicit
metal/punk style before it may be a private review lead. All times remain
unknown: a bare H20:30 on Atabal pages is NOT documented as show start.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin,urlsplit

BASE="https://www.atabal-biarritz.fr/agenda/concerts/"
MONTH={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
       "juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}
WEEKDAY=r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
URL_DATE=re.compile(r"-(?:"+WEEKDAY+r")-(\d{1,2})-("+ "|".join(MONTH)+r")-(20\d\d)/")
DATE=re.compile(r"\b(\d{1,2})\s+("+ "|".join(MONTH)+r")\s+(20\d\d)\b")
GENRE=re.compile(r"\b(post punk|punk rock|punk|hardcore|h core|sludge metal|"
                 r"metal|heavy metal|deathcore|metalcore|hard rock|"
                 r"grindcore|stoner|doom|thrash)\b")
DEFINITE=re.compile(r"\b(annule|annulee|concert annule|supprime|deprogramme)\b")
FEST=re.compile(r"\b(festival|fest|open air)\b")
REMOTENESS=re.compile(r"\b(gare du midi|la mamisele|saubrigues|"
                      r"hors les murs|autre lieu)\b")
VOID={"area","base","br","col","embed","hr","img","input","link","meta",
      "param","source","track","wbr"}

def flat(v):
    return unicodedata.normalize("NFKD",str(v or "")).encode(
        "ascii","ignore").decode("ascii").lower()

def norm(v):
    return " ".join(re.findall("[a-z0-9]+",flat(v)))

def link_ok(href,base=BASE):
    target=urljoin(base,href or "")
    u=urlsplit(target)
    if (u.scheme=="https" and u.hostname=="www.atabal-biarritz.fr"
        and not u.username and not u.password and not u.port
        and not u.query and not u.fragment
        and u.path.startswith("/agenda/concerts/")
        and re.fullmatch(r"/agenda/concerts/[a-z0-9-]{15,220}/",u.path)
        and URL_DATE.search(u.path)):
        return target
    return None

def slug_day(url):
    match=URL_DATE.search(urlsplit(url).path)
    if not match:return None
    day,month,year=match.groups()
    try:return dt.date(int(year),MONTH[month],int(day))
    except ValueError:return None

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            v=link_ok(dict(attrs).get("href"))
            if v and v not in self.links:self.links.append(v)

def cards(html):
    p=Links();p.feed(html)
    return [{"url":url,"date":slug_day(url).isoformat(),
             "slug":urlsplit(url).path.split("/")[-2]}
            for url in p.links if slug_day(url)]

class Event(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active=False
        self.depth=0
        self.heading=None
        self.hdepth=0
        self.main_title=[]
        self.title_captured=False
        self.content=[]
        self.first_h5=[]
        self.headings=[]
        self.stack=[]
        self.stop=False
        self.leadin=[]
    def handle_starttag(self,tag,attrs):
        if self.stop:return
        if not self.active:
            if tag=="article":
                self.active=True;self.depth=1;self.stack=[None]
            return
        if tag not in VOID:
            self.depth+=1
            self.stack.append(tag)
        if tag=="h1" and self.heading is None and not self.title_captured:
            self.heading="h1";self.hdepth=self.depth
    def handle_data(self,text):
        if not self.active or self.stop:return
        t=" ".join(text.split())
        if not t:return
        if norm(t).startswith("vous devriez aimer"):
            self.stop=True;return
        self.content.append(t)
        if len(" ".join(self.leadin))<400:self.leadin.append(t)
        if self.heading:self.main_title.append(t)
        if self.stack and self.stack[-1]=="h5":self.first_h5.append(t)
        if self.stack and self.stack[-1] in ("h1","h2","h3"):
            self.headings.append((self.stack[-1],t))
    def handle_endtag(self,tag):
        if not self.active or tag in VOID or not self.stack:return
        self.stack.pop()
        self.depth-=1
        if tag=="h1" and self.heading is not None:
            self.heading=None
            self.title_captured=True
        if self.depth==0:self.active=False

def candidate(html,url,card,source,today):
    if link_ok(url)!=url:raise ValueError("Event URL not exact Atabal first party")
    if (norm(source.get("name"))!="atabal" or
        norm(source.get("city"))!="biarritz" or
        str(source.get("department"))!="64"):
        raise ValueError("Source identity mismatch")
    date=slug_day(url)
    if not date or card.get("date")!=date.isoformat() or date<dt.date.fromisoformat(today):
        raise ValueError("Bad or past agenda day")
    p=Event();p.feed(html)
    title=" ".join(p.main_title).strip()
    if not title or not p.content:raise ValueError("No single official event content")
    # Event first visible date must match slug; reject stale reposts,
    # notably Atabal's outdated 'LEE FIELDS ... février 2026' slug.
    first=" ".join(p.leadin)
    matches=DATE.findall(flat(first))
    if not matches:
        raise ValueError("Details have no date")
    first_day=matches[0]
    if dt.date(int(first_day[2]),MONTH[first_day[1]],int(first_day[0]))!=date:
        raise ValueError("Official headline date contradicts agenda slug")
    if FEST.search(norm(title)) or FEST.search(norm(card["slug"])):
        raise ValueError("Festival must use Festivals catalogue")
    if REMOTENESS.search(norm(first)):
        raise ValueError("Offsite event, not at Atabal building")
    # Text after page header can contain previous postponed date, not
    # grounds for ignoring the new announced date. But cancellations fail.
    text=norm(" ".join(p.content))
    if DEFINITE.search(text):
        raise ValueError("Cancelled bill must not be advertised")
    # Genre is checked only in THIS event's official content, before
    # recommendations, not in common website boilerplate.
    # The official style label (<h5>) is the only admissible genre source.
    # A reggae/pop artist may mention punk or metal in a biography without
    # performing those styles. Never classify from such passing references.
    genre=GENRE.search(norm(" ".join(p.first_h5)))
    if not genre:raise ValueError("Genre not explicitly tagged by official venue")
    # Atabal says 20H30 but does not specify start versus doors; do not guess.
    slug=urlsplit(url).path.split("/")[-2]
    classification={"h core":"Hardcore","sludge metal":"Sludge Metal",
                    "punk rock":"Punk Rock","post punk":"Post Punk"}.get(
                    genre.group(0),genre.group(0).title())
    return {"candidateId":f"atabal:{date.isoformat()}:{slug}",
        "source":"agenda_officiel_atabal_detail","sourceUrl":url,
        "sourcePage":source["url"],"name":title,
        "leadArtist":title.split(" + ")[0],
        "date":date.isoformat(),"localTime":None,
        "venue":"Atabal","venueCatalogueId":"atabal-biarritz",
        "city":"Biarritz","department":"64",
        "classification":[classification],
        "sourceConfidence":"Fiche officielle date/genre confirmées; heure non qualifiée; validation indépendante obligatoire",
        "officialDetailFound":True,"genreToConfirm":False,
        "reviewRequired":True,"publicationAllowed":False}
