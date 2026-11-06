"""Collecte prudente des calendriers de concerts individuels de La Malterie.

L'agenda officiel publie des liens /fr/evenement/{id}/ical.
Chaque fichier correspond à un événement, contrairement aux flux RSS.
Pas de déduction de date ni de publication automatique.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
import urllib.parse
from feeds import ics_candidates


PATH_RE = re.compile(r"^/fr/evenement/[0-9]+/ical/?$", re.I)


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            value = dict(attrs).get("href")
            if value:
                self.hrefs.append(value)


def ics_event_urls(page, base, limit=12):
    """Uniquement liens https du même site, chemins Drupal événement/ical."""
    parsed = Links()
    parsed.feed(page)
    base_url = urllib.parse.urlsplit(base)
    found = []
    for href in parsed.hrefs:
        absolute = urllib.parse.urljoin(base, href).split("#", 1)[0]
        u = urllib.parse.urlsplit(absolute)
        if (u.scheme == "https"
            and u.hostname and base_url.hostname
            and u.hostname.lower().removeprefix("www.") ==
                base_url.hostname.lower().removeprefix("www.")
            and PATH_RE.fullmatch(u.path)
            and not u.query and
            not any(urllib.parse.urlsplit(x).path == u.path for x in found)):
            found.append(absolute)
        if len(found) >= limit:
            break
    return found


def event_records(ical_body, event_url, venue, day):
    """Un calendrier individuel malterie = 0 ou 1 piste non publiable."""
    items = ics_candidates(ical_body, venue, event_url, day, limit=3)
    if len(items) != 1:
        # Aucun événement ou plusieurs dates = ambigu, retenir zéro.
        return []
    one = items[0]
    one["source"] = "agenda_officiel_malterie_ical"
    one["sourceConfidence"] = "Calendrier individuel officiel; genre, affiche et lieu à revérifier"
    one["genreToConfirm"] = True
    one["venueToConfirm"] = True
    one["publicationAllowed"] = False
    one["reviewRequired"] = True
    one["sourcePage"] = venue.get("url")
    return [one]


# Lecture de repli : le site affiche aussi titre + date complète dans la liste.
import datetime as _dt
import html as _html
import unicodedata as _unicodedata

DATE_RE = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|"
    r"ao[uû]t|septembre|octobre|novembre|d[ée]cembre)\s+(20\d{2})\b",
    re.I)
METAL_RE = re.compile(
    r"\b(black[\s-]*metal|death[\s-]*metal|indus[\s-]*black|synth[\s-]*doom|"
    r"doom|punk|hardcore|metalcore|metal|grind|sludge|stoner|thrash)\b",re.I)
MONTHS = {"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,"juin":6,
          "juillet":7,"aout":8,"septembre":9,"octobre":10,
          "novembre":11,"decembre":12}


def _normalize(value):
    value=_unicodedata.normalize("NFKD",str(value).casefold())
    return value.encode("ascii","ignore").decode("ascii")


class MalterieHeadings(HTMLParser):
    """Capture uniquement fermetures h2/p, sans compter balises HTML void."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture=None
        self.fragments=[]
        self.heading=None
        self.heading_link=None
        self.current_link=None
        self.rows=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ("h2","p") and self.capture is None:
            self.capture=tag
            self.fragments=[]
            if tag=="h2":
                self.heading_link=None
        elif tag=="a" and self.capture=="h2" and attrs.get("href"):
            self.heading_link=attrs["href"]

    def handle_data(self,data):
        if self.capture:
            self.fragments.append(data)

    def handle_endtag(self,tag):
        if self.capture != tag:
            return
        value=" ".join(" ".join(self.fragments).split())
        if tag=="h2":
            self.heading=value if value and value!="Concerts" else None
            self.current_link=self.heading_link
        elif tag=="p" and self.heading:
            if DATE_RE.search(_normalize(value)):
                self.rows.append((self.heading,value,self.current_link))
                self.heading=None
                self.current_link=None
        self.capture=None


def list_fallback_candidates(page,base_url,venue,today):
    """Retient seulement les titres possédant DATE COMPLETE et genre dans le titre."""
    parser=MalterieHeadings()
    parser.feed(page)
    results=[]
    seen=set()
    for headline,context,href in parser.rows:
        if not METAL_RE.search(_normalize(headline)):
            continue
        date_match=DATE_RE.search(_normalize(context))
        if not date_match:
            continue
        try:
            date=_dt.date(int(date_match.group(3)),
                          MONTHS[date_match.group(2)],
                          int(date_match.group(1))).isoformat()
        except (ValueError,KeyError):
            continue
        if date<today or len(headline)>230:
            continue
        ref=base_url
        if href:
            full=urllib.parse.urljoin(base_url,href)
            pp=urllib.parse.urlsplit(full)
            base=urllib.parse.urlsplit(base_url)
            if (pp.scheme=="https" and pp.hostname and base.hostname
                and pp.hostname.lower().removeprefix("www.")==
                    base.hostname.lower().removeprefix("www.")
                and pp.path.startswith("/evenement/concert/")):
                ref=full.split("#",1)[0]
        key=(date,_normalize(headline))
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "candidateId":"malterie-list:"+date+":"+
                re.sub(r"[^a-z0-9]+","-",_normalize(headline))[:68],
            "source":"agenda_officiel_malterie_liste",
            "sourceUrl":ref,"sourcePage":base_url,
            "date":date,"name":_html.unescape(headline),
            "leadArtist":_html.unescape(headline),
            "venue":venue["name"],"city":venue["city"],
            "department":venue["department"],
            "genreToConfirm":True,"venueToConfirm":True,
            "reviewRequired":True,"publicationAllowed":False,
            "sourceConfidence":"Titre et date explicites sur agenda officiel, genre et affiche à revoir",
        })
    return results


DETAIL_PATH = re.compile(r"^/evenement/concert/[^/?#]+/?$",re.I)


def detail_urls(page, base, limit=24):
    """Fiches de concerts sur le même domaine, sans iframe ni redirection tierce."""
    links=Links()
    links.feed(page)
    origin=urllib.parse.urlsplit(base)
    found=[]
    for href in links.hrefs:
        candidate=urllib.parse.urljoin(base,href).split("#",1)[0]
        u=urllib.parse.urlsplit(candidate)
        if (u.scheme=="https" and u.hostname and origin.hostname
            and u.hostname.lower().removeprefix("www.")==
                origin.hostname.lower().removeprefix("www.")
            and DETAIL_PATH.fullmatch(u.path) and not u.query
            and not any(urllib.parse.urlsplit(x).path==u.path for x in found)):
            found.append(candidate)
        if len(found)>=limit:
            break
    return found
