"""La Carène (Brest) SPIP official concert discovery. READ ONLY.

Cards at /-agenda-.html and ?debut_agenda=25 carry their *own* day/month/year.
The matching individual HTML page must confirm the bill, day/month, physical
venue and explicitly punk/metal genre. A festival is never an ordinary show.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin,urlsplit

HOST="www.lacarene.fr"
BASE="https://www.lacarene.fr/-agenda-.html"
EVENT_PATH=re.compile(r"/[a-z0-9-]{5,140}\.html")
MONTHS=dict(zip(("janvier","fevrier","mars","avril","mai","juin","juillet",
    "aout","septembre","octobre","novembre","decembre"),range(1,13)))
DATE_PART=re.compile(r"\b([0-3]?\d)\s+("+"|".join(MONTHS)+r")\b")
START=re.compile(r"\bdebut\s*:\s*([01]?\d|2[0-3]):([0-5]\d)\b")
GENRE=re.compile(r"\b(post punk|post metal|punk|hardcore|metal|metalcore|"
    r"deathcore|hard rock|stoner|sludge|grindcore|thrash|doom|grunge)\b")
FEST=re.compile(r"\b(festival|fest|open air)\b")
BLOCK=re.compile(r"\b(annule|annulee|reporte|reportee|hors les murs|"
    r"atelier|formation|rencontre|conference|stage)\b")
VENUE=re.compile(r"\b(club carene|grande salle carene|grande salle|la carene)\b")
VOID={"area","base","br","col","hr","img","input","link","meta","source"}

def flat(value):
    return unicodedata.normalize("NFKD",str(value or "")).encode(
        "ascii","ignore").decode("ascii").lower()
def norm(value):
    return " ".join(re.findall(r"[a-z0-9]+",flat(value)))

def official_link(href,base=BASE):
    url=urljoin(base,href or "")
    p=urlsplit(url)
    return url if (p.scheme=="https" and p.hostname==HOST and not p.username
        and not p.password and not p.port and not p.query and not p.fragment
        and EVENT_PATH.fullmatch(p.path) and
        p.path not in ("/-agenda-.html","/index.html")) else None

class Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth=0
        self.active=None
        self.stack=[]
        self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        classes=(a.get("class") or "").split()
        if self.active is None:
            if tag=="li" and "item" in classes and "evenement" in classes:
                self.active={"href":None,"values":[],"date":[],"kind":[]}
                self.depth=1
                self.stack=[None]
            return
        part=next((s for s in ("jour","mois","annee") if s in classes),None)
        if "genre" in classes and "bordure" in classes:part="kind"
        if tag=="a" and self.active["href"] is None:
            self.active["href"]=official_link(a.get("href"))
        if tag not in VOID:
            self.depth+=1
            self.stack.append(part)
    def handle_data(self,value):
        if self.active is None:return
        text=value.strip()
        if not text:return
        self.active["values"].append(text)
        field=next((f for f in reversed(self.stack) if f),None)
        if field in ("jour","mois","annee"):
            self.active["date"].append((field,text))
        if field=="kind":self.active["kind"].append(text)
    def handle_endtag(self,tag):
        if self.active is None or tag in VOID or not self.stack:return
        self.stack.pop()
        self.depth-=1
        if self.depth==0:
            self.rows.append(self.active)
            self.active=None
            self.stack=[]

def agenda_cards(html):
    p=Cards();p.feed(html)
    seen=set()
    out=[]
    for row in p.rows:
        url=row["href"]
        if not url or url in seen:continue
        day_parts={k:[] for k in ("jour","mois","annee")}
        for key,val in row["date"]:
            day_parts[key].append(val)
        if any(len(v)!=1 for v in day_parts.values()):
            continue # No date, or more than one date in a multi-day festival
        try:
            dd,mm,yy=(int(day_parts[k][0]) for k in ("jour","mois","annee"))
            date=dt.date(2000+yy if yy<100 else yy,mm,dd)
        except (ValueError,TypeError):continue
        if "concert" not in norm(" ".join(row["kind"])):continue
        name=" ".join(row["values"])
        if len(name)<8:continue
        out.append({"url":url,"date":date.isoformat(),"label":name[:1200],
                    "festivalContext":bool(FEST.search(norm(name))),
                    "cancellationNotice":bool(BLOCK.search(norm(name)))})
        seen.add(url)
    return out

class Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_event=False
        self.depth=0
        self.tags=[]
        self.heading=[]
        self.content=[]
        self.in_heading=False
        self.venue_info=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("main","article") and not self.in_event:
            self.in_event=True
            self.depth=1
            self.tags=[None]
            return
        if not self.in_event:return
        if tag not in VOID:
            self.depth+=1
            self.tags.append("venue_info" if "infos-evenement" in
                            (a.get("class") or "").split() else tag)
        if tag=="h1":self.in_heading=True
    def handle_data(self,data):
        if not self.in_event:return
        text=" ".join(data.split())
        if text:
            self.content.append(text)
            if "venue_info" in self.tags:self.venue_info.append(text)
            if self.in_heading:self.heading.append(text)
    def handle_endtag(self,tag):
        if not self.in_event or tag in VOID or not self.tags:return
        self.tags.pop()
        if tag=="h1":self.in_heading=False
        self.depth-=1
        if self.depth==0:self.in_event=False

def candidate(html,url,card,source,today):
    if official_link(url)!=url:raise ValueError("Individual URL not allowed")
    if (norm(source.get("name"))!="la carene" or
        norm(source.get("city"))!="brest" or str(source.get("department"))!="29"):
        raise ValueError("Venue source mismatch")
    date=dt.date.fromisoformat(card["date"])
    if date<dt.date.fromisoformat(today):raise ValueError("Past date")
    if card.get("festivalContext") or card.get("cancellationNotice"):
        raise ValueError("Festival, cancellation or nonconcert")
    p=Detail();p.feed(html)
    title=" ".join(p.heading).strip()
    text=" ".join(p.content)
    # The page's footer and 'Prochainement' listings must not provide genre
    # evidence, a concert date or an imagined physical venue.
    raw=flat(text)
    cutoff=re.search(r"\bvenir a la carene\b|\bprochainement\b",raw)
    if cutoff:raw=raw[:cutoff.start()]
    if not title or len(raw)<70:
        raise ValueError("Specific official concert page missing")
    if FEST.search(norm(title)):
        raise ValueError("Festival title must go to Festivals pipeline")
    if BLOCK.search(norm(raw[:500])):
        raise ValueError("Cancelled, moved or nonconcert")
    headline=norm(title)
    cardname=norm(card["label"])
    if not headline or headline not in cardname:
        raise ValueError("Different agenda and detail headline")
    # Detail page often omits the year: the dated agenda provides the year
    # and the first-party individual page explicitly repeats the same day/month.
    markers=DATE_PART.findall(raw)
    day_month={(int(day),MONTHS[mon]) for day,mon in markers if mon in MONTHS}
    if (date.day,date.month) not in day_month:
        raise ValueError("Individual page date and card disagree")
    # Venue is asserted only in event-specific 'details' content, NOT from
    # a generic 'Venir à La Carène' site footer.
    if not VENUE.search(norm(" ".join(p.venue_info))):
        raise ValueError("Physical Carène room not present in event-specific room block")
    genre=GENRE.search(norm(raw))
    if not genre:raise ValueError("Official concert subgenre not documented")
    starts=START.findall(raw)
    clock=(f"{int(starts[0][0]):02d}:{starts[0][1]}"
           if len(starts)==1 else None)
    slug=urlsplit(url).path.split("/")[-1][:-5]
    return {"candidateId":f"carene:{date.isoformat()}:{slug}",
        "source":"agenda_officiel_carene_detail","sourceUrl":url,
        "sourcePage":source["url"],"name":title,"leadArtist":title.split(" + ")[0],
        "date":date.isoformat(),"localTime":clock,
        "venue":"La Carène","city":"Brest","department":"29",
        "venueCatalogueId":"la-carene-brest",
        "classification":[genre.group(0).title()],
        "officialDetailFound":True,"reviewRequired":True,
        "publicationAllowed":False,
        "sourceConfidence":"Date et style de fiche officielle, événement hors festival, salle à approuver séparément"}
