"""Read-only La Boule Noire official individual event discovery.

The public listing does not certify music genres. A detail must contain an
exact full ISO calendar date and the corresponding French date and a
relevant genre clue, but the genre and entire lineup stay unapproved.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin,urlsplit

HOST="laboule-noire.fr"
DETAIL=re.compile(r"/[a-z0-9-]+/",re.I)
ISO=re.compile(r"(?<!\d)(20\d\d)-([01]\d)-([0-3]\d)\s+([012]\d):([0-5]\d):([0-5]\d)(?!\d)")
LONG=re.compile(r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\s+(20\d\d)\b")
MONTH={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}
MUSIC=re.compile(r"\b(metalcore|deathcore|hardcore|newcore|metal|punk|post metal|stoner|sludge|grindcore|thrash|doom|nu metal)\b",re.I)
CANCEL=re.compile(r"\b(annule|annulee|annulation|reporte|reportee|deplace|deplacee|cancelled|postponed)\b")

def norm(value):
    t=unicodedata.normalize("NFKD",str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",t.encode("ascii","ignore").decode("ascii")))

def safe(url,listing=False):
    u=urlsplit(url)
    if (u.scheme!="https" or u.hostname not in (HOST,"www."+HOST)
            or u.username or u.password or u.port or u.query or u.fragment):
        return False
    if listing:return u.path=="/"
    return DETAIL.fullmatch(u.path) is not None and u.path not in (
        "/programmation/","/billetterie/","/infos-pratiques/",
        "/mentions-legales/","/vie-privee/")

class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden=0;self.title=0;self.heading=0
        self.titles=[];self.headings=[];self.chunks=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):self.hidden+=1
        if tag=="title":self.title+=1
        if tag=="h1":self.heading+=1
        if tag=="a" and not self.hidden:
            ref=dict(attrs).get("href")
            if ref:self.links.append(ref)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg") and self.hidden:self.hidden-=1
        if tag=="title" and self.title:self.title-=1
        if tag=="h1" and self.heading:self.heading-=1
    def handle_data(self,data):
        t=" ".join(data.split()).strip()
        if not t or self.hidden:return
        if self.title:self.titles.append(t)
        else:
            self.chunks.append(t)
            if self.heading:self.headings.append(t)

def detail_links(html,url,limit=100):
    if not safe(url,listing=True):raise ValueError("Unexpected Boule Noire listing")
    p=Visible();p.feed(html);result=[];seen=set()
    for href in p.links:
        target=urljoin(url,href)
        if safe(target) and target not in seen:
            seen.add(target);result.append(target)
            if len(result)>=max(1,min(120,limit)):break
    return result

def detail_candidate(html,url,source,today):
    if not safe(url):raise ValueError("Untrusted event URL")
    if (source.get("name"),source.get("city"),source.get("url"))!=(
        "La Boule Noire","Paris","https://laboule-noire.fr/"):
        raise ValueError("Wrong venue identity")
    p=Visible();p.feed(html)
    heads=[x for x in p.headings if len(norm(x))>=3 and "boule noire" not in norm(x)]
    if len(set(norm(x) for x in heads))!=1:raise ValueError("No unique event headline")
    act=heads[0].strip()
    text=" ".join(p.chunks)
    if len(text)<100 or CANCEL.search(norm(text[:5000])):
        raise ValueError("Incomplete, canceled or moved concert")
    # The 120 boulevard address is published on the same first-party
    # site's official homepage and infos-pratiques page, not necessarily
    # repeated within individual event articles. Use its unique official
    # page title + exact first-party host + original listing identity;
    # do NOT substitute a neighboring La Cigale event.
    html_title=norm(" ".join(p.titles))
    if html_title != norm(act + " - La Boule Noire"):
        raise ValueError("Venue-specific official title missing")
    if "la cigale" in norm(text[:250]):
        raise ValueError("Another venue shown on first-party event page")
    if MUSIC.search(norm(text[:4500])) is None:
        raise ValueError("Not a relevant metal/punk/hardcore discovery")
    dates=set()
    for m in ISO.finditer(text[:3000]):
        try:dates.add(dt.date(int(m[1]),int(m[2]),int(m[3])).isoformat())
        except ValueError:pass
    frdates=set()
    for m in LONG.finditer(norm(text[:3000])):
        try:frdates.add(dt.date(int(m[3]),MONTH[m[2]],int(m[1])).isoformat())
        except (ValueError,KeyError):pass
    if len(dates)!=1 or dates!=frdates:
        raise ValueError("No matching full ISO and French official event date")
    date=next(iter(dates))
    if dt.date.fromisoformat(date)<dt.date.fromisoformat(str(today)):
        raise ValueError("Past concert")
    return {
        "candidateId":"boule-noire:"+date+":"+urlsplit(url).path.strip("/"),
        "source":"agenda_officiel_boule_noire_detail",
        "sourceUrl":url,"sourcePage":source["url"],
        "date":date,"localTime":None,"name":act,"leadArtist":act,
        "venue":"La Boule Noire","city":"Paris","department":"75",
        "classification":[],"genreToConfirm":True,"lineupToConfirm":True,
        "publicationAllowed":False,"reviewRequired":True,
        "sourceConfidence":"Fiche officielle individuelle, date française et ISO concordantes ; "
            "genre, programmation et horaire exact restent à revérifier."
    }
