"""Conservative read-only discovery from La Maroquinerie's first-party details.

A year-free calendar card or a historical biography year is not an event date.
Moving a show to another venue is a hard rejection, never a confirmed event.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, parse_qsl

HOST="www.lamaroquinerie.fr"
AGENDA="/fr/agenda/"
DETAIL=re.compile(r"/fr/agenda/view/[1-9]\d{0,7}/[a-z0-9-]+/", re.I)
DATE=re.compile(r"\b([0-3]?\d)\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+(20\d\d)\b",re.I)
MONTH={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,"juillet":7,
       "aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}
MUSIC=re.compile(r"\b(metal|metalcore|hardcore|punk|post metal|post-metal|deathcore|stoner|sludge|thrash|doom|industrial|industriel|grindcore|black metal|death metal)\b",re.I)
CANCEL=re.compile(r"\b(annul[eé]e?|annulation|report[eé]e?|d[eé]plac[eé]e?|changement de salle|cancelled|postponed|relocated)\b",re.I)
EXPLICIT=re.compile(r"(?:retrouvez|concert de|concert du|se produira|sur sc[eè]ne le)\s+(.{2,90}?)\s+le\s+([0-3]?\d\s+\w+\s+20\d\d)\s+(?:à|a|au)\s+la\s+maroquinerie\b",re.I)
ALT=re.compile(r"([0-3]?\d\s+\w+\s+20\d\d)\s+(?:à|a|au)\s+la\s+maroquinerie\b",re.I)

def norm(value):
    t=unicodedata.normalize("NFKD",str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",t.encode("ascii","ignore").decode("ascii")))

def valid_url(url,listing=False):
    u=urlsplit(url)
    if (u.scheme!="https" or u.hostname!=HOST or u.username or u.password
        or u.port or u.fragment):
        return False
    if listing:
        return u.path==AGENDA and not u.query
    if not DETAIL.fullmatch(u.path):return False
    if not u.query:return True
    pairs=parse_qsl(u.query,keep_blank_values=True)
    return len(pairs)==1 and pairs[0][0]=="of" and re.fullmatch(r"[0-9]{1,4}",pairs[0][1]) is not None

class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden=0;self.title_depth=0;self.titles=[];self.chunks=[];self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","svg","noscript"):self.hidden+=1
        if tag=="title":self.title_depth+=1
        if tag=="a" and not self.hidden:
            href=dict(attrs).get("href")
            if href:self.links.append(href)
    def handle_endtag(self,tag):
        if tag in ("script","style","svg","noscript") and self.hidden:self.hidden-=1
        if tag=="title" and self.title_depth:self.title_depth-=1
    def handle_data(self,data):
        t=" ".join(data.split())
        if not t or self.hidden:return
        if self.title_depth:self.titles.append(t)
        else:self.chunks.append(t)

def detail_links(html,url,limit=120):
    if not valid_url(url,listing=True):raise ValueError("Untrusted Maroquinerie listing")
    p=Visible();p.feed(html)
    results=[];seen=set()
    for href in p.links:
        link=urljoin(url,href)
        if valid_url(link) and link not in seen:
            seen.add(link);results.append(link)
            if len(results)>=max(1,min(150,limit)):break
    return results

class Calendar(HTMLParser):
    """Read official calendar month/year heading and event <li> together."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.h3=[]
        self.rows=[]
        self.row=None
        self.current_tag=None
        self.buffer=[]
        self.depth=0
    def handle_starttag(self,tag,attrs):
        if tag=="li" and self.row is None:
            self.row={"title":"","day":"","links":[],"text":[]}
            self.depth=1
        elif tag=="li" and self.row is not None:
            self.depth+=1
        if tag in ("h2","h3") and self.current_tag is None:
            self.current_tag=tag
            self.buffer=[]
        if tag=="a" and self.row is not None:
            url=dict(attrs).get("href")
            if url:self.row["links"].append(url)
    def handle_data(self,data):
        value=" ".join(data.split()).strip()
        if not value:return
        if self.current_tag:
            self.buffer.append(value)
        if self.row is not None:self.row["text"].append(value)
    def handle_endtag(self,tag):
        if tag==self.current_tag:
            val=" ".join(self.buffer).strip()
            if self.row is not None:
                if tag=="h2" and not self.row["title"]:
                    self.row["title"]=val
                if tag=="h3" and not self.row["day"]:
                    self.row["day"]=val
            elif tag=="h3":
                self.h3.append(norm(val))
            self.current_tag=None
            self.buffer=[]
        if tag=="li" and self.row is not None:
            self.depth-=1
            if self.depth==0:
                self.rows.append(self.row)
                self.row=None

def verified_calendar_dates(html,url):
    """Conservative first-party cross-proof, limited to its shown month.

    Do not infer future January 2027 from November 2026 calendar heading.
    A year is accepted only for rows in that explicitly displayed month.
    """
    if not valid_url(url,listing=True):
        raise ValueError("Untrusted official calendar")
    p=Calendar();p.feed(html)
    months=[m for h in p.h3 for m in MONTH if norm(m) in h.split()]
    years=[int(h) for h in p.h3 if re.fullmatch(r"20\d\d",h)]
    if len(months)!=1 or len(years)!=1:
        return {}
    selected_month=MONTH[months[0]]
    year=years[0]
    found={}
    for row in p.rows:
        day=norm(row["day"])
        match=re.fullmatch(r"([0-3]?\d)\s+([a-z]+)",day)
        if not match or MONTH.get(match[2])!=selected_month:
            continue
        if not row["title"] or CANCEL.search(" ".join(row["text"])[:650]):
            continue
        try:
            date=dt.date(year,selected_month,int(match[1])).isoformat()
        except ValueError:
            continue
        for href in row["links"]:
            u=urljoin(url,href)
            if not valid_url(u):
                continue
            if u in found and found[u][0]!=date:
                raise ValueError("Inconsistent calendar listing for one detail URL")
            found[u]=(date,norm(row["title"]))
    return found

def detail_candidate(html,url,source,today,calendar_proof=None):
    if not valid_url(url):raise ValueError("Untrusted Maroquinerie detail")
    if (source.get("name"),source.get("city"),source.get("url")) != (
        "La Maroquinerie","Paris","https://www.lamaroquinerie.fr/fr/agenda/"):
        raise ValueError("Wrong source identity")
    p=Visible();p.feed(html)
    # Unique first-party HTML title is an event identity, not the site header.
    title=" ".join(p.titles).strip()
    match=re.fullmatch(r"(.{2,120}?)\s+-\s+La Maroquinerie\s+-\s+Agenda",title,re.I)
    if not match:raise ValueError("Not a specific official concert detail")
    act=match[1].strip()
    if norm(act) in ("la maroquinerie","agenda") or CANCEL.search(act):
        raise ValueError("Unclear show title")
    body=" ".join(p.chunks)
    if len(body)<100 or CANCEL.search(body[:6000]):
        raise ValueError("Show canceled or moved or incomplete")
    if not ("23 rue boyer" in norm(body) and "75020 paris" in norm(body)):
        raise ValueError("Venue address absent")
    if MUSIC.search(body[:5000]) is None:
        raise ValueError("Genre not potentially relevant; review not emitted")
    # Full year MUST be written in a passage explicitly associating that
    # date with this event, and that place. Footer and album years do not count.
    dates=[]
    for m in EXPLICIT.finditer(body[:8500]):
        if norm(act) not in norm(m[1]):continue
        date_phrase=m[2]
        d=DATE.search(date_phrase)
        if d:
            dates.append(d)
    # Additional generic "on D/M/Y at La Maroquinerie" is too vague to
    # attach to a specific headliner; do not promote it.
    parsed=set()
    for m in dates:
        try:parsed.add(dt.date(int(m[3]),MONTH[norm(m[2])],int(m[1])).isoformat())
        except (ValueError,KeyError):pass
    # A detail without the year may be corroborated by a second first-party
    # observation in the official date-scoped *current-month* calendar.
    # Calendar and full named detail must agree when both carry a full date.
    if calendar_proof is not None:
        if (not isinstance(calendar_proof,(list,tuple))
            or len(calendar_proof)!=2
            or norm(calendar_proof[1])!=norm(act)
            or not re.fullmatch(r"20\d\d-\d\d-\d\d",str(calendar_proof[0]))):
            raise ValueError("Calendar row does not match official concert")
        if parsed and parsed!={calendar_proof[0]}:
            raise ValueError("Detail disagrees with dated official calendar")
        parsed.add(calendar_proof[0])
    if len(parsed)!=1:
        raise ValueError("Official full event date not proved on detail or calendar")
    date=next(iter(parsed))
    if dt.date.fromisoformat(date)<dt.date.fromisoformat(str(today)):
        raise ValueError("Past concert")
    return {
        "candidateId":"maroquinerie:"+date+":"+urlsplit(url).path.rstrip("/").split("/")[-2],
        "source":"agenda_officiel_maroquinerie_detail",
        "sourceUrl":url,"sourcePage":source["url"],"date":date,
        "localTime":None,"name":act,"leadArtist":act,
        "venue":"La Maroquinerie","city":"Paris","department":"75",
        "classification":[],"genreToConfirm":True,"lineupToConfirm":True,
        "publicationAllowed":False,"reviewRequired":True,
        "sourceConfidence":"Date et tête d'affiche corroborées sur la fiche officielle ; "
            "genre, soutien, heure et statut à confirmer séparément. Aucun changement de salle supposé."
    }
