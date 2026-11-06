"""Rocher de Palmer: bounded official agenda and per-event discovery, NO approval.

The Drupal agenda has dated <a href="/agenda/slug"> cards with .evt-date
data-day/month/year; individual .node--type-evenement pages carry category,
headliner and named in-venue session information. Never infer dates or the
actual venue from a recommendation, generic site header or third-party page.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

HOST="lerocherdepalmer.fr"
VENUE="le-rocher-de-palmer-cenon"
AGENDA="https://lerocherdepalmer.fr/agenda"
PATH=re.compile(r"/agenda/[a-z0-9-]{3,120}/?")
MONTHS={"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
        "juillet":7,"aout":8,"septembre":9,"octobre":10,"novembre":11,"decembre":12}
VOID={"area","base","br","col","embed","hr","img","input","link","meta",
      "param","source","track","wbr"}
GENRE=re.compile(r"(?<!\w)(?:metal|punk|hard[\s-]?rock|hardcore|"
                 r"post[\s-]?punk|post[\s-]?metal|stoner|grindcore|"
                 r"deathcore|metalcore|thrash|sludge|doom)(?!\w)")
BLOCK=re.compile(r"\b(?:annule|annulee|reporte|reportee|hors les murs|"
                 r"festival|masterclass|atelier|tba)\b")


def flat(value):
    return unicodedata.normalize("NFKD",str(value or "")).encode(
        "ascii","ignore").decode("ascii").casefold()


def norm(value):
    return " ".join(re.findall(r"[a-z0-9]+",flat(value)))


def exact_link(href,base=AGENDA):
    target=urljoin(base,href or "")
    u=urlsplit(target)
    if (u.scheme=="https" and u.hostname==HOST and not u.username
            and not u.password and not u.port and not u.query and not u.fragment
            and PATH.fullmatch(u.path) and u.path not in
            ("/agenda/archives","/agenda/micro-folie")):
        return target
    return None


def event_day(attrs):
    if not all(x in attrs for x in ("data-day","data-month","data-year")):
        return None
    try:
        return dt.date(int(attrs["data-year"]),MONTHS[flat(attrs["data-month"])],
                       int(attrs["data-day"]))
    except (KeyError,TypeError,ValueError):
        return None


class CardParser(HTMLParser):
    def __init__(self,base):
        super().__init__(convert_charrefs=True)
        self.base=base
        self.depth=0
        self.current=None
        self.cards=[]

    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if not self.depth:
            link=exact_link(a.get("href"),self.base) if tag=="a" else None
            # A unique dated card is required; footer and related event
            # links do not carry dates and are rejected at the finish stage.
            if link and a.get("aria-label"):
                self.current={"url":link,"name":" ".join(a["aria-label"].split()),
                              "dates":[],"text":[],"labels":[]}
                self.depth=1
            return
        if all(x in a for x in ("data-day","data-month","data-year")):
            day=event_day(a)
            if day is not None:
                self.current["dates"].append(day)
        if a.get("data-term-name"):
            self.current["labels"].append(flat(a["data-term-name"]))
        if tag not in VOID:
            self.depth+=1

    def handle_data(self,data):
        if self.depth and self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self,tag):
        if not self.depth or tag in VOID:
            return
        self.depth-=1
        if self.depth==0:
            row=self.current
            self.current=None
            if row and len(set(row["dates"]))==1 and len(row["name"])>=3:
                row["date"]=row["dates"][0].isoformat()
                row["cardText"]=" ".join(" ".join(row["text"]).split())[:2500]
                row.pop("dates",None)
                row.pop("text",None)
                self.cards.append(row)


def agenda_cards(page,base=AGENDA):
    p=CardParser(base)
    p.feed(page)
    seen=set()
    rows=[]
    for row in p.cards:
        if row["url"] in seen:
            continue
        seen.add(row["url"])
        rows.append(row)
    return rows


def card_priority(card):
    """A read priority only, never an approval or proof of event genre."""
    if BLOCK.search(norm(card["cardText"])):
        return -100
    if "metal-punk" in card["labels"]:
        return 2
    if GENRE.search(norm(card["cardText"])):
        return 1
    return 0


class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article=False
        self.depth=0
        self.capture=None
        self.capture_depth=0
        self.bits=[]
        self.doc={"dates":[],"name":[],"venue":[],"categories":[],"descriptions":[],
                  "sessionStart":[],"visible":[],"label":[],
                  "h1VisibleStart":None,"h1VisibleEnd":None}
        self.end_content=False

    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        classes=(a.get("class") or "").split()
        if not self.in_article:
            if tag=="article" and "node--type-evenement" in classes:
                self.in_article=True
                self.depth=1
            return
        if tag not in VOID:
            self.depth+=1
        if self.end_content:
            return
        if self.capture:
            if tag not in VOID:
                self.capture_depth+=1
        if "data-term-name" in a and ("full--evt-categories" not in classes):
            # Terms are captured as global tags only within this event page,
            # never inferred from the menu's category <option> list.
            self.doc["label"].append(flat(a["data-term-name"]))
        if ("evt-date" in classes or "lb_session-date" in classes):
            date=event_day(a)
            if date:
                self.doc["dates"].append(date)
        field=None
        if tag=="h1" and not self.capture:
            field="name"
            self.doc["h1VisibleStart"]=len(self.doc["visible"])
        elif "lb_session--evt-location-location" in classes and not self.capture:
            field="venue"
        elif ("field--name-field-intro" in classes or
              "field--name-field-texte" in classes) and not self.capture:
            field="descriptions"
        elif "full--evt-categories" in classes and not self.capture:
            field="categories"
        elif "full--evt-hours" in classes and not self.capture:
            field="sessionStart"
        if field:
            self.capture=field
            self.capture_depth=1
            self.bits=[]

    def handle_data(self,value):
        if self.in_article and not self.end_content:
            # Avoid using common footer site description as genre proof.
            if norm(value)=="vous aimerez aussi":
                self.end_content=True
                return
            self.doc["visible"].append(value)
            if self.capture:
                self.bits.append(value)

    def handle_endtag(self,tag):
        if not self.in_article or tag in VOID:
            return
        if self.capture:
            self.capture_depth-=1
            if self.capture_depth==0:
                text=" ".join(" ".join(self.bits).split())
                if self.capture=="name":
                    self.doc["h1VisibleEnd"]=len(self.doc["visible"])
                if text:
                    self.doc[self.capture].append(text)
                self.capture=None
                self.bits=[]
        self.depth-=1
        if self.depth==0:
            self.in_article=False

def parse_detail(page):
    p=DetailParser()
    p.feed(page)
    return p.doc



def official_bill(row, card):
    """Read named acts from the event H1 and the immediate '+ ACT' line.

    Accessible agenda labels sometimes contain ONLY the headline act. A
    first-party named support cannot be silently lost; uncertain billings
    remain private and cannot be approved from agenda/biography alone.
    """
    card_name=" ".join(str(card.get("name") or "").split())
    parts=[x.strip() for x in re.split(r"\s+\+\s+",card_name)]
    if not 1 <= len(parts) <= 5:
        raise ValueError("Programmation nominative trop longue ou absente")
    heading=row["name"][0]
    if norm(parts[0]) not in norm(heading):
        raise ValueError("Titre de tête d'affiche incohérent entre agenda et détail")
    # HTML <h1> may be split into nested spans/strong tags or the artist
    # may appear in earlier biographies. Capture its exact token boundary
    # while parsing, never locate it by searching for duplicate text.
    start,end=row.get("h1VisibleStart"),row.get("h1VisibleEnd")
    if (not isinstance(start,int) or not isinstance(end,int)
            or not 0<=start<end<=len(row["visible"])):
        raise ValueError("Délimitation du H1 événement officiel absente")
    visible=[str(x).strip() for x in row["visible"] if str(x).strip()]
    following=[str(x).strip() for x in row["visible"][end:end+5]
               if str(x).strip()][:2]
    if following and following[0].startswith("+"):
        first=following[0]
        suffix=first[1:].strip() if first!="+" else (
            following[1] if len(following)>1 else "")
        if not suffix or len(suffix)>150:
            raise ValueError("Première partie non identifiée")
        named=[x.strip() for x in re.split(r"\s+\+\s+",suffix)]
        if not 1<=len(named)<=4:
            raise ValueError("Plateau officiel ambigu")
        if len(parts)>1:
            if [norm(x) for x in parts[1:]] != [norm(x) for x in named]:
                raise ValueError("Programmation différente entre agenda et détail")
        else:
            parts.extend(named)
    elif len(parts)>1:
        # The entire bill must then be explicitly present in the event H1.
        if not all(norm(x) in norm(heading) for x in parts[1:]):
            raise ValueError("Premières parties non confirmées par la fiche")
    unsafe=re.compile(r"\b(?:guest|guests|tba|a confirmer|premiere partie|"
                      r"1ere partie|invite surprise|support act)\b")
    if (any(not 3<=len(norm(x))<=100 or unsafe.search(norm(x))
            for x in parts)
            or len({norm(x) for x in parts})!=len(parts)):
        raise ValueError("Programmation provisoire ou artistes non identifiés")
    # A support is advertised in this event but the H1 has only a headliner.
    if len(parts)==1 and any(norm(x) in
            ("1ere partie","premiere partie","support act")
            for x in visible):
        raise ValueError("Première partie annoncée sans artiste identifié")
    return " + ".join(parts),parts


def detail_candidate(page,url,card,source,today):
    if exact_link(url)!=url:
        raise ValueError("Fiche événement pas sur le domaine autorisé")
    if (norm(source.get("name"))!="le rocher de palmer" or
            norm(source.get("city"))!="cenon" or str(source.get("department"))!="33"):
        raise ValueError("Salle de la veille non reconnue")
    row=parse_detail(page)
    dates=set(row["dates"])
    if len(dates)!=1:
        raise ValueError("Fiche individuelle sans session unique datée")
    date=next(iter(dates))
    if date<dt.date.fromisoformat(today) or date.isoformat()!=card["date"]:
        raise ValueError("Date officielle ou agenda incohérent")
    if len(row["name"])!=1:
        raise ValueError("Titre officiel unique absent")
    clean,artist_names=official_bill(row,card)
    if len(row["venue"])!=1 or norm(row["venue"][0])!="le rocher de palmer":
        raise ValueError("Salle réelle absente ou hors les murs")
    content=norm(" ".join(row["visible"]))
    # A band biography can mention a festival without this event being one.
    # Reject only event-specific status labels and the named bill itself.
    status_labels=" ".join(row["label"] + card.get("labels", []))
    if BLOCK.search(norm(status_labels)) or BLOCK.search(norm(card["name"])):
        raise ValueError("Annonce annulée, reportée, festival ou hors les murs")
    categories={norm(x) for x in row["categories"]}
    labels={x for x in row["label"]}
    description=norm(" ".join(row["descriptions"]))
    # First-party categories are authoritative. A biography can mention an
    # artist's former punk/metal career even when TODAY's event is reggae,
    # jazz, hip-hop or comedy; never turn that historical text into genre
    # evidence. Fallback to a biography is allowed only for a BROAD ROCK
    # category on the SAME official event, e.g. rock -> hard rock.
    # Keep exact categories rather than a loosely tokenized page-wide genre.
    from_category="metal-punk" in labels or "metal punk" in categories
    category_genre=next((GENRE.search(cat) for cat in sorted(categories)
                         if GENRE.search(cat)),None)
    broad_rock=any(re.fullmatch(r"rock(?: [a-z]+){0,3}",cat)
                   and not re.search(r"\b(?:reggae|dub|rap|hip hop|jazz|"
                                     r"electro|techno|soul|rnb|pop)\b",cat)
                   for cat in categories)
    detailed=GENRE.search(description) if broad_rock else None
    if from_category:
        genre="Metal, Punk"
    elif category_genre:
        genre=category_genre.group(0).title()
    elif detailed:
        genre=detailed.group(0).title()
    else:
        raise ValueError("Genre métal/punk non établi par la catégorie officielle")
    # Time means 'concert start' only if explicitly stated. The agenda's
    # first clock is not necessarily door/show time.
    time_match=re.findall(
        r"\bdebut (?:du|des|de) concerts?\s*:\s*([01]\d|2[0-3]):([0-5]\d)\b",
        flat(" ".join(row["visible"])))
    when=f"{time_match[0][0]}:{time_match[0][1]}" if len(time_match)==1 else None
    slug=urlsplit(url).path.split("/")[-1]
    return {
        "candidateId":f"rocher-palmer:{date.isoformat()}:{slug}",
        "source":"agenda_officiel_rocher_de_palmer_detail",
        "sourceUrl":url,"sourcePage":source["url"],
        "name":clean,"leadArtist":artist_names[0],
        "officialArtistNames":artist_names,
        "lineupEvidence":"event-h1-and-immediate-named-official-suffix",
        "date":date.isoformat(),"localTime":when,"venue":"Le Rocher de Palmer",
        "venueCatalogueId":VENUE,"city":"Cenon","department":"33",
        "classification":[genre],"genreToConfirm":False,
        "sourceConfidence":"Fiche individuelle officielle : genre et lieu explicites, vérification indépendante obligatoire",
        "reviewRequired":True,"publicationAllowed":False,"officialDetailFound":True,
    }
