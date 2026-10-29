"""Acceptation stricte: date/titre/lieu officiels en JSON-LD et coordonnées connues.
Si un contrôle ne peut pas être effectué, la fiche reste en attente.
"""
import json
import math
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

HOSTS = {
    "mpt.montpellier.fr", "www.opera-bordeaux.com",
    "billetterie.opera-bordeaux.com", "www.paris.fr",
    "philharmoniedeparis.fr", "www.philharmoniedeparis.fr",
}

def norm(s):
    t = unicodedata.normalize("NFKD", str(s).lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if not unicodedata.combining(c))).split())

def names(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b and (a == b or (len(a) >= 9 and len(b) >= 9 and (a in b or b in a))
                or SequenceMatcher(None, a, b).ratio() > .87))

def meters(a, b):
    a1, a2 = map(math.radians, a)
    b1, b2 = map(math.radians, b)
    k = math.sin((a1-b1)/2)**2 + math.cos(a1)*math.cos(b1)*math.sin((a2-b2)/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(k)))

class LD(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.parts = []; self.blocks = []
    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower().strip() == "application/ld+json"
            self.parts = []
    def handle_data(self, data):
        if self.active: self.parts.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.blocks.append("".join(self.parts)); self.active = False

def walk(v):
    if isinstance(v, list):
        for e in v: yield from walk(e)
    elif isinstance(v, dict):
        yield v
        if "@graph" in v: yield from walk(v["@graph"])

def proof(ev, originals):
    """Ne considère jamais une URL seule comme une preuve."""
    p = urlparse(ev["source_url"])
    if p.scheme != "https" or p.hostname not in HOSTS or p.username or p.password:
        return False, "domaine officiel non approuvé"
    try:
        req = Request(ev["source_url"], headers={"User-Agent":"OndesPublicDataAudit/1.0"})
        with urlopen(req, timeout=20) as r:
            if urlparse(r.geturl()).hostname != p.hostname:
                return False, "redirection de domaine"
            raw = r.read(1_500_001)
            if len(raw) > 1_500_000: return False, "page trop volumineuse"
            html = raw.decode("utf-8", errors="replace")
    except Exception:
        return False, "source officielle inaccessible"
    parser = LD(); parser.feed(html)
    for block in parser.blocks:
        try: obj = json.loads(block)
        except (ValueError, TypeError): continue
        for node in walk(obj):
            types = node.get("@type", [])
            if isinstance(types, str): types = [types]
            if not any(str(t).lower().endswith("event") for t in types): continue
            if not names(node.get("name", ""), ev["title"]): continue
            place = node.get("location")
            places = place if isinstance(place, list) else [place]
            for loc in places:
                if not isinstance(loc, dict) or not names(loc.get("name", ""), ev["venue"]): continue
                try:
                    start = date.fromisoformat(str(node["startDate"])[:10])
                    end = date.fromisoformat(str(node.get("endDate", node["startDate"]))[:10])
                except (ValueError, KeyError, TypeError): continue
                if start.isoformat() != ev["date_start"] or end.isoformat() != ev["date_end"]: continue
                # GPS: preuve fournie par la fiche officielle ou coordonnées d'un même lieu déjà public.
                geo = loc.get("geo") if isinstance(loc.get("geo"), dict) else {}
                try:
                    point = (float(geo["latitude"]), float(geo["longitude"]))
                    if meters(point, (ev["lat"], ev["lng"])) <= 75:
                        return True, "JSON-LD officiel et GPS"
                except (TypeError, KeyError, ValueError, OverflowError): pass
                for old in originals:
                    if norm(old.get("city", "")) != norm(ev["city"]) or not names(old.get("venue", ""), ev["venue"]):
                        continue
                    try:
                        if meters((float(old["lat"]), float(old["lng"])), (ev["lat"], ev["lng"])) <= 50:
                            return True, "JSON-LD officiel et lieu déjà public"
                    except (TypeError, KeyError, ValueError, OverflowError): continue
    return False, "preuve structurée de date, titre, lieu et GPS insuffisante"
