"""Antipode Rennes: bounded first-party agenda + named detail, review only.

No published catalogue write. The year is accepted ONLY from the dated agenda
card; biographies, current date and the event URL slug never supply a year.
Door time and explicit musical start are different fields. A sold-out concert
is not cancelled. Festival stages and multi-day festival passes are excluded.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://antipode-rennes.fr/agenda"
HOST = "antipode-rennes.fr"
EVENT_PATH = re.compile(r"/agenda/([A-Za-z0-9][A-Za-z0-9-]{1,130})/?")
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area"}
BAD = re.compile(r"\b(?:atelier|conference|formation|exposition|rencontre|stage|spectacle|festival)\b")
FESTIVAL = re.compile(r"\b(?:kool thing|festival|open air|fest(?:ival)?)\b")
MUSIC = re.compile(
    r"\b(?:rock|metal|punk|hardcore|stoner|doom|sludge|noise|shoegaze|"
    r"psych(?:edelique)?|grunge|indie|garage|post rock|hard rock)\b")
CONCERT = re.compile(r"\b(?:concert|apero concert)\b")
CANCELLED = re.compile(r"\b(?:annule|annulee|cancelled|canceled|annulation)\b")
POSTPONED = re.compile(r"\b(?:reporte|reportee|postponed|rescheduled)\b")
MONTHS = {
    "janv":1,"janvier":1,"fevr":2,"fevrier":2,"mars":3,"avr":4,"avril":4,
    "mai":5,"juin":6,"juil":7,"juillet":7,"aout":8,"sept":9,
    "septembre":9,"oct":10,"octobre":10,"nov":11,"novembre":11,
    "dec":12,"decembre":12,
}
MONTH_NAMES = "|".join(sorted(MONTHS,key=len,reverse=True))
DATE = re.compile(
    r"(?<!\d)([0-3]?\d)\s+("+MONTH_NAMES+r")\.?\s+(20\d{2})(?!\d)")
ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})(?:T\d{2}:\d{2})?\b")
CLOCK = r"([01]?\d|2[0-3])\s*[h:]\s*([0-5]\d)"
START = re.compile(r"\bdebut\s+des?\s+concerts?\s*:\s*"+CLOCK)
DOORS = re.compile(r"\bouverture\s+des?\s+portes\s*:\s*"+CLOCK)


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value or "")).casefold()
        ).encode("ascii","ignore").decode("ascii").replace("\xa0"," ")


def plain(value):
    return " ".join(re.findall(r"[a-z0-9]+", fold(value)))


def official_link(href,base=AGENDA):
    url=urljoin(base,href or "")
    p=urlsplit(url)
    if (p.scheme!="https" or p.hostname!=HOST or p.username or p.password
            or p.port or p.query or p.fragment or not EVENT_PATH.fullmatch(p.path)
            or p.path.rstrip("/") in ("/agenda/archives","/agenda/accueil")):
        return None
    return url


def valid_agenda(url):
    p=urlsplit(url)
    # No verified pagination scheme currently exists for this website.
    return (p.scheme=="https" and p.hostname==HOST and p.path=="/agenda"
            and not (p.query or p.fragment or p.username or p.password or p.port))


def full_dates(text):
    """Return unique full ISO days. A missing year cannot be invented."""
    result=set()
    for d,m,y in DATE.findall(fold(text)):
        try:
            result.add(dt.date(int(y),MONTHS[m],int(d)).isoformat())
        except ValueError:
            pass
    for ymd in ISO_DATE.findall(str(text or "")):
        try:
            result.add(dt.date.fromisoformat(ymd).isoformat())
        except ValueError:
            pass
    return result


class _Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchor=None
        self.hdepth=0
        self.rows=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=="a":
            if self.anchor is not None:
                # A nested anchor cannot safely determine one event card.
                self.anchor["ambiguous"]=True
                return
            u=official_link(attrs.get("href"))
            if u:
                self.anchor={"url":u,"visible":[],"headings":[],"dates":[],
                             "ambiguous":False}
                self.hdepth=0
        if self.anchor:
            if tag in ("h2","h3","h4"):
                self.hdepth+=1
            if tag=="time" and attrs.get("datetime"):
                self.anchor["dates"].append(attrs["datetime"])

    def handle_data(self,value):
        if self.anchor is None:
            return
        text=" ".join(value.split())
        if text:
            self.anchor["visible"].append(text)
            if self.hdepth:
                self.anchor["headings"].append(text)

    def handle_endtag(self,tag):
        if self.anchor is None:
            return
        if tag in ("h2","h3","h4") and self.hdepth:
            self.hdepth-=1
        if tag=="a":
            self.rows.append(self.anchor)
            self.anchor=None
            self.hdepth=0


def agenda_cards(html,url=AGENDA,today="2026-11-03"):
    if not valid_agenda(url):
        raise ValueError("Only the official first-party Antipode agenda is allowed")
    parser=_Cards()
    parser.feed(html)
    now=dt.date.fromisoformat(today)
    accepted={}
    for row in parser.rows:
        if row["ambiguous"] or not row["headings"]:
            continue
        title=" ".join(row["headings"]).strip()
        text=" ".join(row["visible"])
        normalized=plain(text)
        if not 3<=len(title)<=200 or not CONCERT.search(normalized):
            continue
        if BAD.search(plain(title)) or FESTIVAL.search(normalized):
            # Festival stages and multi-day pass belong to Festivals.
            continue
        genre=MUSIC.search(normalized)
        if not genre:
            continue
        dates=set().union(full_dates(text),full_dates(" ".join(row["dates"])))
        if len(dates)!=1:
            continue
        date=next(iter(dates))
        when=dt.date.fromisoformat(date)
        if not now<=when<=now+dt.timedelta(days=540):
            continue
        status=("cancelled" if CANCELLED.search(normalized)
                else "postponed" if POSTPONED.search(normalized)
                else "sold_out" if re.search(r"\bcomplet\b",normalized)
                else "confirmed_unchecked")
        card={"url":row["url"],"title":title,"date":date,
              "classification":genre.group(0).title(),
              "statusNotice":status,
              "evidence":"official_antipode_card_full_year_and_genre"}
        old=accepted.get(card["url"])
        if old and (old["date"]!=date or plain(old["title"])!=plain(title)):
            accepted.pop(card["url"],None)
            continue
        accepted[card["url"]]=card
    return sorted(accepted.values(),key=lambda x:(x["date"],x["url"]))


def selected_cards(cards,known,today,limit=8):
    limit=max(1,min(12,int(limit)))
    distinct={x["url"]:x for x in cards}
    future=sorted(distinct.values(),key=lambda x:(x["date"],x["url"]))
    unseen=[x for x in future if ("officialUrl",x["url"]) not in known]
    existing=[x for x in future if ("officialUrl",x["url"]) in known]
    def rotate(items,count):
        if not items or count<=0:return []
        count=min(count,len(items))
        start=(dt.date.fromisoformat(today).toordinal()*max(1,count))%len(items)
        return [items[(start+i)%len(items)] for i in range(count)]
    # Always allocate room to revisit known shows for sold-out/cancellation news.
    unseen_limit=(limit+1)//2 if existing else limit
    new=rotate(unseen,unseen_limit)
    old=rotate(existing,limit-len(new))
    return new+old+rotate(
        [x for x in unseen if x not in new],limit-len(new)-len(old))


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main=0
        self.in_title=0
        self.skip=0
        self.head=[]
        self.visible=[]

    def handle_starttag(self,tag,attrs):
        if tag=="main": self.in_main+=1
        if tag in ("script","style","nav","footer","noscript"):
            self.skip+=1
        if tag=="h1" and self.in_main:
            self.in_title+=1

    def handle_endtag(self,tag):
        if tag=="h1" and self.in_title:self.in_title-=1
        if tag in ("script","style","nav","footer","noscript") and self.skip:
            self.skip-=1
        if tag=="main" and self.in_main:self.in_main-=1

    def handle_data(self,value):
        if not self.in_main or self.skip:return
        t=" ".join(value.split())
        if t:
            self.visible.append(t)
            if self.in_title:self.head.append(t)


def clock(match):
    if match is None:return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def candidate(html,url,card,source,today):
    if (official_link(url)!=url or card.get("url")!=url
        or source.get("name")!="Antipode" or source.get("city")!="Rennes"
        or str(source.get("department"))!="35"
        or source.get("url")!=AGENDA):
        raise ValueError("Antipode source/venue/URL mismatch")
    if len(full_dates(card.get("date")))!=1 or card["date"] not in full_dates(card["date"]):
        raise ValueError("Full official agenda date is required")
    day=dt.date.fromisoformat(today)
    when=dt.date.fromisoformat(card["date"])
    if not day<=when<=day+dt.timedelta(days=540):
        raise ValueError("Concert outside allowed horizon")
    if not MUSIC.search(plain(card.get("classification"))):
        raise ValueError("No event-specific rock/metal/punk category")
    p=_Detail()
    p.feed(html)
    title=" ".join(p.head).strip()
    if not title or plain(title)!=plain(card.get("title")):
        raise ValueError("Individual official headline differs from dated card")
    raw=" ".join(p.visible)
    bounded=re.split(r"\binformations sur les evenements\b|\bnous vous recommandons\b",
                     fold(raw),maxsplit=1)[0]
    # Two named Antipode music rooms are permitted. Venue footer,
    # biographies and unrelated visits cannot prove the performance room.
    room_match=re.search(r"\bantipode\s*(?:-\s*)?(la grande scene|le club)\b",
                         bounded[:650])
    if not room_match:
        raise ValueError("Named Antipode music room missing in event details")
    venue_hall="Le Club" if room_match.group(1)=="le club" else "La Grande Scène"
    if FESTIVAL.search(plain(title)) or BAD.search(plain(title)):
        raise ValueError("Festival/workshop, not an individual concert")
    detail_days=full_dates(" ".join(p.visible[:25]))
    if detail_days and card["date"] not in detail_days:
        raise ValueError("Calendar date contradicts named event page")
    status=card.get("statusNotice","confirmed_unchecked")
    if CANCELLED.search(plain(title+" "+" ".join(p.visible[:14]))):
        status="cancelled"
    elif POSTPONED.search(plain(title+" "+" ".join(p.visible[:14]))):
        status="postponed"
    starts=list(START.finditer(bounded))
    doors=list(DOORS.finditer(bounded))
    musical_start=clock(starts[0]) if len(starts)==1 else None
    door_time=clock(doors[0]) if len(doors)==1 else None
    m=re.search(r"\borganise par\s+([^;:.]{3,65})",bounded)
    organizer=m.group(1).strip() if m else None
    slug=EVENT_PATH.fullmatch(urlsplit(url).path).group(1)
    name=card["title"]
    lead=re.split(r"\s+\+\s+",name,maxsplit=1)[0].strip()
    # Apéro-concert describes the format, not the artist.
    apero=re.fullmatch(r"ap[eé]ro[- ]concert avec\s+(.+)",lead,flags=re.I)
    if apero:
        lead=apero.group(1).strip()
    return {
        "candidateId":f"antipode:{card['date']}:{slug}",
        "name":name,"leadArtist":lead,"date":card["date"],
        "venue":"Antipode","venueCatalogueId":"antipode-rennes",
        "venueHall":venue_hall,
        "genreEvidenceScope":"official_event_card",
        "city":"Rennes","department":"35",
        "classification":[card["classification"]],
        "source":"agenda_officiel_antipode_detail_review",
        "sourcePage":AGENDA,"sourceUrl":url,
        "organizerToReview":organizer,
        "localTime":musical_start,"doorTime":door_time,
        "timeMeaning":"explicit_music_start" if musical_start else "unverified",
        "soldOutNotice":status=="sold_out",
        "statusNotice":status,
        "cancellationNotice":status in ("cancelled","postponed"),
        "officialDetailFound":True,
        "sourceConfidence":"Official dated calendar + named Antipode room; independent approval still required",
        "reviewRequired":True,"publicationAllowed":False,
    }
