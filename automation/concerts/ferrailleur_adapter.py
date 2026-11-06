"""Le Ferrailleur (Nantes) : découverte prudente depuis l'agenda officiel.

Certaines dates présentent plusieurs concerts simultanés.
En cas de structure ambiguë, nous produisons zéro candidat plutôt que
d'inventer des programmations.
"""
from __future__ import annotations
import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

MONTHS = {"janvier":1,"fevrier":2,"mars":3,"avril":4,"mai":5,
          "juin":6,"juillet":7,"aout":8,"septembre":9,"octobre":10,
          "novembre":11,"decembre":12}
DAY = re.compile(
    r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
    r"\s+(\d{1,2})\s+(janvier|f[ée]vrier|mars|avril|mai|juin|"
    r"juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"
    r"\s*[-–]\s*(\d{1,2}):(\d{2})",re.I)
HEAD = re.compile(
    r"(?:^|\n)\s*(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|"
    r"ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"
    r"\s*\n\s*((?:20)?\d{2})\s*(?:\n|$)",re.I)
EXCLUDED = re.compile(
    r"\b(atelier|masterclass|formation|conference|reunion|blind.test|"
    r"annule|reportee|festival|fest)\b",re.I)
GENRES = ("metal","metalcore","hardcore","punk","grind","sludge",
          "doom","post black","post metal","heavy rock","heavy metal",
          "deathcore","stoner","death metal","black metal")
LOW_VALUE = ("doom festif", "hard techno", "hard groove", "hard bounce")


def normalized(text):
    text=unicodedata.normalize("NFKD",str(text or "").casefold())
    return text.encode("ascii","ignore").decode("ascii")


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"):
            self.skip+=1
        if tag in ("p","li","h1","h2","h3","h4","br","article","section"):
            self.parts.append("\n")
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript"):
            self.skip=max(0,self.skip-1)
        if tag in ("p","li","h1","h2","h3","h4","article","section"):
            self.parts.append("\n")
    def handle_data(self,data):
        if not self.skip and data.strip():
            # Certains groupes et l'année sont dans des noeuds HTML distincts
            # sans espace explicite : séparer les noeuds plutôt que les coller.
            self.parts.append(data)
            self.parts.append("\n")
    def get_text(self):
        return "".join(self.parts)


def metal_genre_line(line):
    label=normalized(line)
    if not label or any(x in label for x in LOW_VALUE):
        return False
    tokens=[x.strip() for x in label.split(",")]
    return bool(tokens and any(
        any(re.search(r"(?<!\w)"+re.escape(g)+r"(?!\w)", t)
            for g in GENRES) for t in tokens
    ))



class OfficialEventLinks(HTMLParser):
    """Match first-party title links exactly, never guess an event URL."""
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.active = None
        self.nesting = 0
        self.parts = []
        self.links = {}

    def handle_starttag(self, tag, attrs):
        params = dict(attrs)
        if self.active:
            if tag not in ("br", "img", "input", "meta", "link", "hr"):
                self.nesting += 1
            return
        if tag != "a":
            return
        full = urljoin(self.base_url, params.get("href") or "")
        parsed, origin = urlsplit(full), urlsplit(self.base_url)
        if (parsed.scheme == "https" and parsed.hostname == origin.hostname
                and re.fullmatch(r"/evenement/[^/?#]+/\d+/?", parsed.path)
                and not parsed.query and not parsed.fragment):
            self.active, self.nesting, self.parts = full, 1, []

    def handle_endtag(self, tag):
        if not self.active:
            return
        self.nesting -= 1
        if self.nesting:
            return
        title = " ".join(" ".join(self.parts).split())
        if title:
            self.links.setdefault(simplify(title), set()).add(self.active)
        self.active, self.parts = None, []

    def handle_data(self, value):
        if self.active:
            self.parts.append(value)


def simplify(value):
    return re.sub(r"[^a-z0-9]+", " ", normalized(value)).strip()


def official_event_urls(page, source_url):
    parser = OfficialEventLinks(source_url)
    parser.feed(page)
    return {name: next(iter(links)) for name, links in parser.links.items()
            if len(links) == 1}



def choose_official_detail(title, date_iso, local_time, card_links):
    """Match a complete event name, and a matching date/time if card includes it.

    Multiple suitable official URLs mean ambiguity: return None. A card must
    match the entire lineup as distinct normalized words, not merely one band.
    """
    name = simplify(title)
    if not name or len(name) < 7:
        return None
    try:
        date = dt.date.fromisoformat(date_iso)
    except (TypeError, ValueError):
        return None
    month = next((key for key, val in MONTHS.items() if val == date.month), None)
    if not month:
        return None
    dd = re.compile(r"\b0?" + str(date.day) + r"\s+" + month + r"\b")
    clock = simplify(local_time)
    urls = set()
    for card, url in card_links.items():
        if not re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", card):
            continue
        # Official event cards can wrap the full schedule or only their title.
        # If other information is displayed, it MUST agree with our candidate.
        has_schedule = bool(re.search(r"\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b", card))
        if has_schedule and not dd.search(card):
            continue
        if has_schedule and clock and not re.search(
            r"(?<![a-z0-9])" + re.escape(clock) + r"(?![a-z0-9])", card
        ):
            continue
        urls.add(url)
    return next(iter(urls)) if len(urls) == 1 else None

def extract_ferrailleur(page, source_url, venue, today):
    parser=VisibleText()
    parser.feed(page)
    text=parser.get_text().replace("\r\n","\n")
    official_links=official_event_urls(page,source_url)
    headers=list(HEAD.finditer(text))
    if not headers:
        return []
    dates=list(DAY.finditer(text))
    # Plusieurs créneaux pour une même date : les sections publiques peuvent
    # mêler concert et DJ set. On exclut la date entière plutôt que d'attribuer
    # l'horaire de la soirée à un groupe.
    from collections import Counter
    repeated=Counter((int(x.group(1)),normalized(x.group(2))) for x in dates)
    data=[]
    seen=set()
    for i,m in enumerate(dates):
        if repeated[(int(m.group(1)),normalized(m.group(2)))]>1:
            continue
        previous=[h for h in headers if h.start()<m.start()]
        if not previous:
            continue
        header=previous[-1]
        hm=normalized(header.group(1))
        em=normalized(m.group(2))
        if hm!=em:
            continue
        year_raw=header.group(2)
        year=int(year_raw) if len(year_raw)==4 else 2000+int(year_raw)
        try:
            day=dt.date(year,MONTHS[em],int(m.group(1))).isoformat()
        except (ValueError,KeyError):
            continue
        if day<today:
            continue
        stop=dates[i+1].start() if i+1<len(dates) else len(text)
        segment=text[m.end():stop]
        before_reservation=re.split(r"\bR[eé]servation\b",segment,maxsplit=1,flags=re.I)[0]
        lines=[" ".join(x.split()) for x in before_reservation.splitlines() if x.strip()]
        lines=[x for x in lines if not re.match(
            r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b",x,re.I
        ) and not re.match(r"^(\d{1,2}:\d{2}|(?:aujourd.hui))",x,re.I)]
        # Le marquage HTML de l'horaire peut laisser une ligne '-' isolée.
        lines=[x for x in lines if x.strip(" -–—•") != ""]
        # Pour éviter de fabriquer des associations groupe/genre, la dernière
        # ligne avant Réservation doit être un champ de genres reconnaissable.
        if len(lines)<2 or not metal_genre_line(lines[-1]):
            continue
        genre=lines[-1]
        names=lines[:-1]
        if (not names or len(names)>6 or
            any(EXCLUDED.search(x) for x in names)):
            continue
        title=" + ".join(names)
        if len(title)>200:
            continue
        key=(day,normalized(title))
        if key in seen:
            continue
        seen.add(key)
        data.append({
            "candidateId":"ferrailleur:"+day+":"+
                          re.sub(r"[^a-z0-9]+","-",normalized(title))[:85],
            "source":"agenda_officiel_ferrailleur_genre",
            "sourceUrl":choose_official_detail(
                title, day, f"{int(m.group(3)):02d}:{m.group(4)}",
                official_links) or source_url,
            "sourcePage":source_url,
            "officialDetailFound":bool(choose_official_detail(
                title, day, f"{int(m.group(3)):02d}:{m.group(4)}",
                official_links)),
            "date":day, "localTime":f"{int(m.group(3)):02d}:{m.group(4)}",
            "name":title, "leadArtist":names[0],
            "venue":venue["name"],"city":venue["city"],
            "department":venue.get("department"),
            "classification":[x.strip() for x in genre.split(",") if x.strip()],
            "genreToConfirm":False,"reviewRequired":True,
            "publicationAllowed":False,
            "sourceConfidence":"Agenda officiel Le Ferrailleur; extraction texte à confirmer sur fiche événement",
        })
    return data


def diagnose_markup(page, source_url="https://www.leferrailleur.fr/agenda"):
    """Mesures publiques uniquement, sans HTML ni donnée utilisateur privée."""
    parser=VisibleText()
    parser.feed(page)
    body=parser.get_text().replace("\r\n","\n")
    dates=list(DAY.finditer(body))
    months=list(HEAD.finditer(body))
    href_events=set(re.findall(
        r"""(?:href=)["']([^"']*/evenement/[^"']+)["']""",page,re.I
    ))
    return {
        "htmlCharacters":len(page),
        "visibleCharacters":len(body),
        "datedEventMarkers":len(dates),
        "monthYearHeaders":len(months),
        "individualEventLinks":len(href_events),
        "exactOfficialTitleLinks":len(official_event_urls(page,source_url)),
        "officialLinkTitleSample":sorted(official_event_urls(page,source_url))[:5],
        "firstEventDates":[m.group(0)[:90] for m in dates[:4]],
        "firstMonthHeaders":[m.group(0).strip() for m in months[:4]],
        "headerContextBeforeFirstDate":(
            body[max(0,dates[0].start()-850):dates[0].start()]
            if dates else ""
        ),
    }
