"""Hydrophone (Lorient) SPIP first-party agenda. Strict nonpublishing discovery.

Cards display day+month without year; year must be supplied by an EXACT
separately verified ticket seller record. Festival "Les Indisciplinées" is
never an ordinary independent concert. Unknown years fail closed.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin,urlsplit

BASE="https://hydrophone.fr/-Agenda-.html"
HOSTS={"hydrophone.fr","www.hydrophone.fr"}
DAYMONTH=re.compile(r"\b(lun|mar|mer|jeu|ven|sam|dim)\.?\s+([0-3]?\d)\s+"
                    r"(janv|fevr|mars|avr|mai|juin|juil|aout|sept|oct|nov|dec)\.?",re.I)
MONTH={m:i+1 for i,m in enumerate(
    ("janv","fevr","mars","avr","mai","juin","juil","aout","sept","oct","nov","dec"))}
WEEK={"lun":0,"mar":1,"mer":2,"jeu":3,"ven":4,"sam":5,"dim":6}
CLOCK=re.compile(r"\b([01]?\d|2[0-3])\s*h\s*([0-5]\d)?\b")
GENRE=re.compile(r"\b(post[\s-]?punk|punk|hardcore|metalcore|metal|deathcore|"
    r"grunge|hard[\s-]?rock|stoner|doom|thrash|sludge|grindcore)\b",re.I)
BLOCK=re.compile(r"\b(annule|annulee|reporte|reportee|conference|"
                 r"rencontre|projection|atelier|scolaire|dessine)\b")
FEST=re.compile(r"\b(indisciplinees|festival|fest|open air)\b")
# Reviewed at the named ticket distributor, not inferred from current date.
# The official Hydrophone page independently confirms the artist/day/month
# and the ticket distributor confirms year, artist, room and full date.
YEAR_PROOFS={
 "https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html":{
   "date":"2027-02-10","time":"20:00",
   "title":"REVNOIR + ICE SEALED EYES",
   "proofUrl":"https://www.fnacspectacles.com/event/"
       "revnoir-sometimes-i-feel-you-sometimes-i-dont-tour-hydrophone-lorient-21627359/",
   "proofType":"authorized-tickets-full-date"
 }
}
VOID={"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}

def normalized(text):
    return " ".join(unicodedata.normalize("NFKD",str(text or ""))
        .encode("ascii","ignore").decode("ascii").lower().split())

def official_url(href,base=BASE):
    u=urljoin(base,href or "")
    p=urlsplit(u)
    if (p.scheme!="https" or p.hostname not in HOSTS or p.username or
        p.password or p.port or p.query or p.fragment or
        not re.fullmatch(r"/[A-Za-z0-9_-]{4,140}\.html",p.path) or
        p.path.lower().startswith(("/-agenda-","/-les-indisciplinees-"))):
        return None
    return "https://hydrophone.fr"+p.path

class Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active=None;self.depth=0;self.in_h3=0;self.in_button=0
        self.h3=[];self.button=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);cls=(a.get("class") or "").split()
        if self.active is None:
            if tag=="div" and "agenda-item" in cls:
                self.active={"url":None,"heading":[],"badges":[]}
                self.depth=1
            return
        if tag=="div":self.depth+=1
        if tag=="a" and self.active["url"] is None:
            self.active["url"]=official_url(a.get("href"))
        if tag=="h3":self.in_h3+=1;self.h3=[]
        if tag=="button":self.in_button+=1;self.button=[]
    def handle_data(self,data):
        if self.active is None:return
        if self.in_h3:self.h3.append(data)
        if self.in_button:self.button.append(data)
    def handle_endtag(self,tag):
        if self.active is None:return
        if tag=="h3" and self.in_h3:
            self.in_h3-=1
            self.active["heading"].append(" ".join(" ".join(self.h3).split()))
        if tag=="button" and self.in_button:
            self.in_button-=1
            self.active["badges"].append(" ".join(" ".join(self.button).split()))
        if tag=="div":
            self.depth-=1
            if self.depth==0:
                self.rows.append(self.active)
                self.active=None
                self.in_h3=0;self.in_button=0

def agenda_cards(html):
    parser=Cards();parser.feed(html)
    result=[];seen=set()
    for x in parser.rows:
        url=x["url"]
        if not url or url in seen:continue
        heads=x["heading"]
        timing=next(((h,m) for h in heads if (m:=DAYMONTH.search(normalized(h)))),None)
        if timing is None:continue
        date_text,date_match=timing
        date_fields=(int(date_match.group(2)),MONTH[date_match.group(3)[:4]],
                     WEEK[date_match.group(1)[:3]])
        category=" ".join(heads)
        label=next((h for h in reversed(heads) if h!=date_text and
                    normalized(h) not in ("concert","concert scolaire")),
                    None)
        if not label or "concert" not in normalized(category):continue
        is_festival=bool(FEST.search(normalized(label+" "+" ".join(x["badges"]))))
        unsuitable=bool(BLOCK.search(normalized(category+" "+" ".join(x["badges"]))))
        time=CLOCK.search(normalized(date_text))
        result.append({"url":url,"title":label,"day":date_fields[0],
            "month":date_fields[1],"weekday":date_fields[2],
            "clock":f"{int(time.group(1)):02d}:{time.group(2) or '00'}" if time else None,
            "festivalContext":is_festival,"blocked":unsuitable,
            "festivalLabel":" ".join(x["badges"])})
        seen.add(url)
    return result

class EventDetail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h1=[];self.h2=[];self.h3=[];self.h4=[];self.parts=[]
        self.current=None;self.buffer=[];self.scope=0
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"):self.skip+=1
        if tag in ("h1","h2","h3","h4"):
            self.current=tag;self.buffer=[]
    def handle_data(self,value):
        if self.skip:return
        t=" ".join(value.split())
        if t:
            self.parts.append(t)
            if self.current:self.buffer.append(t)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript"):self.skip=max(0,self.skip-1)
        if tag==self.current:
            getattr(self,tag).append(" ".join(self.buffer))
            self.current=None;self.buffer=[]

def candidate(html,url,card,source,today):
    if official_url(url)!=url or url!=card.get("url"):
        raise ValueError("Exact first-party event URL mismatch")
    if (normalized(source.get("name"))!="hydrophone" or
        normalized(source.get("city"))!="lorient" or
        str(source.get("department"))!="56"):
        raise ValueError("Venue identity mismatch")
    if card["blocked"] or card["festivalContext"]:
        raise ValueError("Festival, cancellation, offsite or nonconcert")
    p=EventDetail();p.feed(html)
    headline=next((v for v in p.h1 if v.strip()),None)
    if normalized(headline)!=normalized(card["title"]):
        raise ValueError("Individual page does not confirm card headline")
    if "concert" not in {normalized(h) for h in p.h3}:
        raise ValueError("Not an official concert detail")
    dm=next((m for text in p.h2 if
             (m:=DAYMONTH.search(normalized(text)))),None)
    if dm is None or (int(dm.group(2)),MONTH[dm.group(3)[:4]],
        WEEK[dm.group(1)[:3]])!=(card["day"],card["month"],card["weekday"]):
        raise ValueError("Official individual page calendar does not match")
    hour=next((m for h in p.h4 if (m:=CLOCK.search(normalized(h)))),None)
    actual=f"{int(hour.group(1)):02d}:{hour.group(2) or '00'}" if hour else None
    if not actual or card["clock"]!=actual:raise ValueError("Clock mismatch")
    if not any(normalized(h) in ("hydrophone - grande salle","hydrophone - club")
               for h in p.h4):
        raise ValueError("Physical Hydrophone venue room unconfirmed")
    raw=normalized(" ".join(p.parts))
    # No generic taxonomy ("Rock / Métal / Punk") alone, genre must be in
    # the individual bio, but *not* from unrelated website footer.
    stop=raw.find("en voir plus")
    if stop!=-1:raw=raw[:stop]
    genre=GENRE.search(raw)
    if not genre:raise ValueError("Genre not confirmed on official artist page")
    year=YEAR_PROOFS.get(url)
    if not year:raise ValueError("No independent verified year; manual review")
    day=dt.date.fromisoformat(year["date"])
    if (day.day,day.month,day.weekday())!=(
         card["day"],card["month"],card["weekday"]):
        raise ValueError("Ticket proof full date contradicts official agenda")
    if year["time"]!=actual or normalized(year["title"])!=normalized(headline):
        raise ValueError("Ticket proof title/time mismatch")
    if day<dt.date.fromisoformat(today):
        raise ValueError("Past concert")
    slug=urlsplit(url).path.rsplit("/",1)[-1][:-5].lower()
    return {"candidateId":f"hydrophone:{day.isoformat()}:{slug}",
        "source":"hydrophone_first_party_agenda_detail_ticket_year",
        "sourceUrl":url,"sourcePage":source["url"],"name":headline,
        "leadArtist":headline.split(" + ")[0],"date":day.isoformat(),
        "localTime":actual,"venue":"Hydrophone","city":"Lorient",
        "department":"56","venueCatalogueId":"hydrophone-lorient",
        "classification":[genre.group(0).title()],
        "officialDetailFound":True,
        "yearEvidence":year["proofUrl"],
        "yearEvidenceType":year["proofType"],
        "reviewRequired":True,"publicationAllowed":False}
