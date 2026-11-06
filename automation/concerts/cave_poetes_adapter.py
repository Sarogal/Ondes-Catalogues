"""Cave aux Poètes official event details: date, bill, venue, subgenre.
Never approves or publishes; third-party links and recommendations excluded.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re, unicodedata
from urllib.parse import urljoin,urlsplit

HOST="caveauxpoetes.com"
EVENT=re.compile(r"/evenement/[a-z0-9-]{3,120}/")
MONTHS=dict(zip(("janvier","fevrier","mars","avril","mai","juin","juillet",
    "aout","septembre","octobre","novembre","decembre"),range(1,13)))
DATE=re.compile(r"\b([0-3]?\d)\s+("+"|".join(MONTHS)+r")\s+(20\d\d)\b")
GENRE=re.compile(r"\b(post punk|punk|hardcore|metalcore|deathcore|hard rock|"
    r"metal|stoner|sludge|grindcore|thrash|doom)\b")
BAD=re.compile(r"\b(annule|annulee|reporte|reportee|festival|atelier|"
    r"masterclass|formation)\b")
START=re.compile(r"\bconcerts?\s*:\s*([01]?\d|2[0-3])\s*h\s*([0-5]\d)?\b")
VOID={"area","base","br","col","hr","img","input","link","meta","source"}

def plain(s):
    return unicodedata.normalize("NFKD",str(s or "")).encode(
        "ascii","ignore").decode().lower()
def norm(s):return " ".join(re.findall(r"[a-z0-9]+",plain(s)))
def url_ok(href,base="https://caveauxpoetes.com/agenda/"):
    url=urljoin(base,href or "")
    p=urlsplit(url)
    return url if (p.scheme=="https" and p.hostname==HOST and not p.username
        and not p.password and not p.port and not p.query and not p.fragment
        and EVENT.fullmatch(p.path)) else None
def date_of(s):
    matches=DATE.findall(plain(s))
    if len(matches)!=1:return None
    d,m,y=matches[0]
    try:return dt.date(int(y),MONTHS[m],int(d))
    except ValueError:return None

def field(tag,a,detail):
    cl=(a.get("class") or "").split()
    ident=a.get("id")
    if "artistehome" in cl and detail:return "artist"
    if "titartprog" in cl and not detail:return "artist"
    if detail:
        if ident=="date":return "date"
        if "lelieu" in cl:return "venue"
        if ident=="horaire":return "times"
        if ident=="artdesc":return "biography"
        if ident=="lestags":return "tags"
        if ident=="nomsoiree":return "event_kind"
    else:
        if ident=="ladateevtprog":return "date"
        if "lelieuevtprog" in cl:return "venue"
        if ident=="legenreevt":return "tags"
    if "infosbill" in cl:return "status"
    return None

class Page(HTMLParser):
    def __init__(self,detail=False):
        super().__init__(convert_charrefs=True)
        self.detail=detail;self.current=None;self.stack=[]
        self.rows=[];self.fields={};self.names=[];self.depth=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if self.current is None:
            if self.detail:
                if tag!="article" or "evenement" not in (a.get("class") or "").split():return
                self.current={"url":None}
            else:
                if tag!="a" or "unevt" not in (a.get("class") or "").split():return
                link=url_ok(a.get("href"))
                if not link:return
                self.current={"url":link}
            self.depth=1;self.stack=[None];self.fields={};self.names=[]
            return
        f=field(tag,a,self.detail)
        if tag not in VOID:
            self.depth+=1;self.stack.append(f)
        if f=="artist":self.fields["_artist"]=[]
    def handle_data(self,text):
        if self.current is None:return
        f=next((x for x in reversed(self.stack) if x),None)
        if f:self.fields.setdefault("_artist" if f=="artist" else f,[]).append(text)
    def handle_endtag(self,tag):
        if self.current is None or tag in VOID or not self.stack:return
        f=self.stack.pop()
        if f=="artist":
            name=" ".join(" ".join(self.fields.pop("_artist",[])).split())
            if name and name not in self.names:self.names.append(name)
        self.depth-=1
        if self.depth==0:
            data=dict(self.current)
            data.update({k:" ".join(" ".join(v).split()) for k,v in self.fields.items()
                         if k!="_artist"})
            data["artists"]=self.names[:]
            self.rows.append(data);self.current=None;self.stack=[]

def cards(html):
    parser=Page()
    parser.feed(html)
    found=[];seen=set()
    for row in parser.rows:
        date=date_of(row.get("date"))
        if date and row["artists"] and row["url"] not in seen:
            row["date"]=date.isoformat()
            found.append(row);seen.add(row["url"])
    return found

def candidate(html,url,card,source,today):
    if url_ok(url)!=url:raise ValueError("Invalid official detail URL")
    if (norm(source.get("name"))!="la cave aux poetes" or
        norm(source.get("city"))!="roubaix" or str(source.get("department"))!="59"):
        raise ValueError("Source location mismatch")
    parser=Page(detail=True);parser.feed(html)
    if len(parser.rows)!=1:raise ValueError("Missing single event article")
    row=parser.rows[0]
    date=date_of(row.get("date"))
    if not date or date.isoformat()!=card["date"] or date<dt.date.fromisoformat(today):
        raise ValueError("Event date mismatch or past")
    if (not row["artists"] or [norm(a) for a in row["artists"]]
        !=[norm(a) for a in card["artists"]]):
        raise ValueError("Event lineup mismatch")
    if (norm(row.get("venue"))!="la cave aux poetes" or
        norm(card.get("venue"))!="la cave aux poetes"):
        raise ValueError("Outside Cave venue")
    if BAD.search(norm(" ".join((card.get("status",""),row.get("status",""),
                                  row.get("event_kind",""))))):
        raise ValueError("Festival or cancelled event")
    # Rock / Métal / Punk as a generic calendar category is NOT genre proof.
    match=GENRE.search(norm(row.get("tags",""))) or GENRE.search(
        norm(row.get("biography","")))
    if not match:raise ValueError("Subgenre not proven by first-party bill")
    times=START.findall(plain(row.get("times","")))
    hour=(f"{int(times[0][0]):02d}:{times[0][1] or '00'}"
          if len(times)==1 else None)
    title=" + ".join(row["artists"])
    return {"candidateId":"cave-poetes:"+date.isoformat()+":"+
                urlsplit(url).path.strip("/").split("/")[-1],
        "source":"agenda_officiel_cave_poetes_detail","sourceUrl":url,
        "sourcePage":source["url"],"name":title,"leadArtist":row["artists"][0],
        "date":date.isoformat(),"localTime":hour,
        "venue":"La Cave aux Poètes","venueCatalogueId":"la-cave-aux-poetes-roubaix",
        "city":"Roubaix","department":"59","classification":[match.group(0).title()],
        "officialDetailFound":True,"genreToConfirm":False,
        "reviewRequired":True,"publicationAllowed":False,
        "sourceConfidence":"Fiche officielle individuelle ; relecture indépendante obligatoire"}
