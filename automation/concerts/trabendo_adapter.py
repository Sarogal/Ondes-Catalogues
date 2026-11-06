"""Read-only discovery from Trabendo's own agenda and individual event pages.

No inferred year, opening time, support artists, cancellation or public approval.
The generic agenda supplies URLs only. Individual event pages must explicitly
confirm a full French date, the venue and an allowed genre label.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOST="www.letrabendo.net"
LIST="/programmation/"
DETAIL=re.compile(r"/programmation/[a-z0-9-]+/",re.I)
GENRES={"metal","metalcore","heavy metal","punk","punk rock","punk-rock",
        "punk hardcore","punk-hardcore","hardcore","post hardcore","post-hardcore",
        "death metal","black metal","doom","stoner","sludge","thrash"}
MONTHS={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
        "juillet":7,"aout":8,"septembre":9,"octobre":10,
        "novembre":11,"decembre":12}
DATE=re.compile(r"^([0-3]?\d)\s+"
                r"(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
                r"\s+(20\d{2})$",re.I)
CANCEL=re.compile(r"\b(annule|annulee|annulation|reporte|reportee|cancelled|postponed)\b")

def norm(s):
    s=unicodedata.normalize("NFKD",str(s or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",s.encode("ascii","ignore").decode("ascii")))

def safe(url, listing=False):
    u=urlsplit(url)
    if (u.scheme!="https" or u.hostname!=HOST or u.username or u.password
        or u.port or u.query or u.fragment):
        return False
    return u.path==LIST if listing else DETAIL.fullmatch(u.path) is not None

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
        self.fragments=[]
        self.hidden=0
        self.in_title=0
        self.title=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","svg","noscript"):
            self.hidden+=1
        if tag=="title":
            self.in_title+=1
        if tag=="a" and not self.hidden:
            h=dict(attrs).get("href")
            if h:self.links.append(h)
    def handle_endtag(self,tag):
        if tag in ("script","style","svg","noscript") and self.hidden:self.hidden-=1
        if tag=="title" and self.in_title:self.in_title-=1
    def handle_data(self,value):
        t=" ".join(value.split()).strip()
        if not t or self.hidden:return
        if self.in_title:self.title.append(t)
        else:self.fragments.append(t)

def detail_links(html, url, cap=100):
    if not safe(url,True):raise ValueError("Untrusted Trabendo agenda")
    p=Parser();p.feed(html)
    links=[];seen=set()
    for href in p.links:
        candidate=urljoin(url,href)
        if safe(candidate) and candidate not in seen:
            seen.add(candidate);links.append(candidate)
            if len(links)>=max(1,min(150,cap)):break
    return links

class TaggedLinks(HTMLParser):
    """Capture the first-party category displayed inside each agenda link.

    Used ONLY for scan priority; it never validates genre or authorizes
    publication. Keep nested link text, ignore scripts/styles.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items=[]
        self.current=None
        self.parts=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
        if tag=="a" and not self.hidden:
            self.current=dict(attrs).get("href")
            self.parts=[]
    def handle_endtag(self,tag):
        if tag=="a" and self.current is not None:
            self.items.append((self.current," ".join(self.parts)))
            self.current=None;self.parts=[]
        if tag in ("script","style","noscript","svg") and self.hidden:
            self.hidden-=1
    def handle_data(self,data):
        if self.current is not None and not self.hidden and data.strip():
            self.parts.append(data.strip())

# The agenda's genre badges may be written "punk-rock", "post-hardcore",
# etc. This is strictly a scheduling signal, not a proof of genre.
PRIORITY=re.compile(
    r"\b(metal|metalcore|heavy metal|death metal|black metal|hardcore|"
    r"post hardcore|punk|punk rock|punk hardcore|thrash|doom|stoner|sludge)\b")

def categorized_detail_links(html,listing):
    links=detail_links(html,listing)
    p=TaggedLinks();p.feed(html)
    labels={}
    for href,label in p.items:
        url=urljoin(listing,href)
        if url in links:
            labels.setdefault(url,[]).append(norm(label))
    preferred=[]
    secondary=[]
    for url in links:
        captions=labels.get(url,[])
        if any("concert" in label and PRIORITY.search(label) for label in captions):
            preferred.append(url)
        else:
            secondary.append(url)
    return preferred,secondary


def detail_candidate(html,url,source,today):
    if not safe(url):raise ValueError("Untrusted concert URL")
    if (source.get("name"),source.get("city"),source.get("url")) != (
        "Le Trabendo","Paris","https://www.letrabendo.net/programmation/"):
        raise ValueError("Venue identity mismatch")
    doc=Parser();doc.feed(html)
    fragments=doc.fragments
    # Only accept an explicitly named concert/genre/date/venue record,
    # not a snippet in scripts or a footer/copyright year.
    text=" ".join(fragments)
    if not text:
        raise ValueError("Concert incomplete")
    # Real Trabendo pages split parts of the date and category across
    # nested HTML elements. Matching one HTMLParser.handle_data() fragment
    # per field silently rejects every real show. Reassemble visible text
    # in document order, but require a STRICT local event-card sequence.
    # Reject neighbouring "Vous devriez aimer" recommendations: the
    # event title MUST match the one unique first-party <title>.
    import re
    heading=" ".join(doc.title).strip()
    title_match=re.fullmatch(
        r"\s*(.{2,120}?)\s*[–—-]\s*Trabendo\s*",heading,re.I)
    if not title_match:
        raise ValueError("Official unique Trabendo event title absent")
    act=title_match[1].strip()
    artist=norm(act)
    if artist in ("programmation","travaux","le trabendo") or CANCEL.search(artist):
        raise ValueError("Unexpected Trabendo event identity")
    # Ignore the venue’s recommendation carousel, which may advertise a
    # second concert with another date or genre.
    joined=norm(text).split("vous devriez aimer",1)[0]
    if CANCEL.search(joined):
        raise ValueError("Cancellation or venue change requires human review")
    # The venue name, event date and genre must occur consecutively in
    # THIS event's own card, never inferred from an unrelated biography.
    month_words="|".join(MONTHS)
    full_date=re.compile(
        r"(?<!\d)([0-3]?\d)\s+("+month_words+r")\s+(20\d{2})(?!\d)")
    allowed=sorted({norm(label) for label in GENRES},key=len,reverse=True)
    genre_words="|".join(re.escape(label) for label in allowed)
    sequence=re.compile(
        r"^\s*"+re.escape(artist)+r"\s+concert\s+("+genre_words+
        r")\s+trabendo\s+salle\s+de\s+concert\b")
    verified=set()
    for match in full_date.finditer(joined):
        try:
            date=dt.date(int(match[3]),MONTHS[match[2]],int(match[1]))
        except ValueError:
            continue
        if date<dt.date.fromisoformat(str(today)):
            continue
        # Limit the card to 220 chars to prevent a matching artist/genre
        # later in a different show or a loose footer.
        segment=joined[match.end():match.end()+220]
        bill=sequence.match(segment)
        if bill:
            verified.add((date.isoformat(),bill[1]))
    if len(verified)!=1:
        raise ValueError("No single dated official event card with matching title and genre")
    date,genre=next(iter(verified))
    return {"candidateId":"trabendo:"+date+":"+urlsplit(url).path.rstrip("/").split("/")[-1],
            "source":"agenda_officiel_trabendo_detail",
            "sourceUrl":url,"sourcePage":source["url"],
            "date":date,"localTime":None,"name":act,"leadArtist":act,
            "venue":"Le Trabendo","city":"Paris","department":"75",
            "classification":[genre],"genreToConfirm":False,
            "lineupToConfirm":True,"publicationAllowed":False,
            "reviewRequired":True,"sourceConfidence":
            "Date, artiste principal, genre et salle vus sur la fiche officielle; "
            "premières parties, annulations éventuelles et horaires à revérifier."}
