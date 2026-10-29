"""Contrôle indépendant HTML (en complément du JSON-LD), sans approximation.
Exige une fiche officielle titrée, dates/horaires, lieu, âge/prix et GPS documentés.
"""
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from proof import norm, HOSTS
from venue_registry import verified_location

MONTHS = ("janvier","février","mars","avril","mai","juin","juillet","août",
          "septembre","octobre","novembre","décembre")
MONTH_SHORT = ("janv","févr","mars","avr","mai","juin","juil","août",
               "sept","oct","nov","déc")

class Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden=0;self.heading=0;self.title=0
        self.words=[];self.headers=[];self.titles=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):self.hidden+=1
        if tag=="h1":self.heading+=1
        if tag=="title":self.title+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg"):self.hidden=max(0,self.hidden-1)
        if tag=="h1":self.heading=max(0,self.heading-1)
        if tag=="title":self.title=max(0,self.title-1)
    def handle_data(self,v):
        s=" ".join(v.split())
        if not s or self.hidden:return
        self.words.append(s)
        if self.heading:self.headers.append(s)
        if self.title:self.titles.append(s)

def read(url):
    parsed=urlparse(url)
    if parsed.scheme!="https" or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        return None,"domaine officiel inconnu"
    try:
        req=Request(url,headers={"User-Agent":"OndesCatalogues-Audit/2.0",
                                "Accept":"text/html,application/xhtml+xml"})
        with urlopen(req,timeout=20) as r:
            if urlparse(r.geturl()).hostname!=parsed.hostname:
                return None,"redirection hors du domaine officiel"
            content=r.read(1_500_001)
            if len(content)>1_500_000:return None,"page officielle trop volumineuse"
            return content.decode("utf-8",errors="replace"),""
    except Exception:
        return None,"page officielle inaccessible"

def date_forms(iso):
    value=date.fromisoformat(iso)
    d,m,y=value.day,value.month,value.year
    return {f"{d:02d}/{m:02d}/{y}",
            f"{d} {MONTHS[m-1]} {y}",
            f"{d} {MONTH_SHORT[m-1]} {y}",
            f"{d} {MONTH_SHORT[m-1]}. {y}",
            f"{d:02d} {MONTHS[m-1]} {y}",
            f"{d:02d} {MONTH_SHORT[m-1]} {y}",
            f"{d:02d} {MONTH_SHORT[m-1]}. {y}"}

def present_date(text,iso):
    normalized=norm(text)
    return any(norm(form) in normalized for form in date_forms(iso))

def visible_time(text,time_value):
    required=set(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b",time_value))
    if not required:return False
    rendered=re.sub(r"(?<!\d)(\d{1,2})\s*[hH]\s*(\d{2})(?!\d)",
                    lambda m:f"{int(m[1]):02d}:{m[2]}",text)
    rendered=re.sub(r"(?<!\d)(\d{1,2})\s*[hH](?!\d)",
                    lambda m:f"{int(m[1]):02d}:00",rendered)
    found={f"{int(h):02d}:{mm}" for h,mm in
           re.findall(r"\b(\d{1,2}):([0-5]\d)\b",rendered)}
    return all(f"{int(v.split(':')[0]):02d}:{v.split(':')[1]}" in found for v in required)

def venue_is_written(event,text):
    venue=norm(event["venue"])
    body=norm(text)
    if venue and venue in body:return True
    if norm(event["city"])=="bordeaux" and "auditorium" in venue:
        return "auditorium" in body
    if "philharmonie" in venue and "salle de conference" in venue:
        return "philharmonie" in body and "salle de conference" in body
    return False

def price_is_written(event,text):
    price=event.get("price","")
    if not price:return True
    body=norm(text)
    p=norm(price)
    if p in body:return True
    if "gratuit" in p:return "gratuit" in body and "inscription" in body
    amounts=re.findall(r"\d+(?:[.,]\d+)?",price)
    return bool(amounts) and all(re.search(r"\b"+re.escape(x)+r"\b",body) for x in amounts)

def age_is_written(event,text):
    minimum=event.get("age_min")
    if minimum is None:return True
    body=norm(text)
    if minimum==0.25:return "3 mois" in body
    if not isinstance(minimum,(float,int)):return False
    return bool(re.search(r"\b"+str(int(minimum))+r"\s+ans\b",body))

def headline_matches(event_title, heading_text):
    """Titre dans la balise officielle title/h1, tolérant une courte précision.
    Par exemple : « Atelier d'éveil musical - Concert du dimanche Classic jazz ».
    """
    expected=norm(event_title).split()
    actual=norm(heading_text).split()
    if not expected or not actual:return False
    if " ".join(expected) in " ".join(actual):return True
    if len(expected)<4:return False
    for start,word in enumerate(actual):
        if word != expected[0]:continue
        i=start
        found=True
        for need in expected[1:]:
            options=actual[i+1:i+5]
            if need not in options:
                found=False
                break
            i=i+1+options.index(need)
        if found:return True
    return False

def verify_event(event,originals):
    # La géolocalisation ne provient jamais de l'IA seule.
    valid_geo,why=verified_location(event)
    if not valid_geo:return False,why
    html,error=read(event["source_url"])
    if html is None:return False,error
    dom=Visible();dom.feed(html)
    heading=norm(" ".join(dom.headers+dom.titles))
    title=norm(event["title"])
    if not headline_matches(event["title"],heading):
        return False,"titre non confirmé en en-tête de la fiche officielle"
    text=" ".join(dom.words)
    if not present_date(text,event["date_start"]) or not present_date(text,event["date_end"]):
        return False,"date complète non confirmée sur la fiche officielle"
    if not venue_is_written(event,text):
        return False,"lieu absent de la fiche officielle"
    if not visible_time(text,str(event.get("time",""))):
        return False,"tous les horaires ne sont pas confirmés"
    if not price_is_written(event,text):
        return False,"tarif non confirmé"
    if not age_is_written(event,text):
        return False,"âge minimum non confirmé"
    # JSON-LD déjà vérifié ? S'il est complet, les contrôles textuels restent obligatoires.
    return True,"page officielle + date(s) + heure(s) + lieu + tarif + âge + GPS documenté"
