#!/usr/bin/env python3
"""Daily read-only follow-up of already PUBLIC Grosses Ondes concerts.

This is an ANOMALY REPORT, not a cancellation detector or publication pipeline.
Only narrow, first-party event detail URLs with a predictable HTML structure
are checked; all generic calendars, media articles and unsupported sources
remain explicitly outside the verified coverage. Neither JSON nor approvals
are ever modified.
"""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

import discover
import official_recheck
import ferrailleur_official
import glazart_adapter
import club_pages
import trabendo_adapter
import maroquinerie_adapter
import boule_noire_adapter
import bonjour_minuit_adapter
import rocher_palmer_adapter

CLOUD = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
MONTHS_EN = dict(zip("jan feb mar apr may jun jul aug sep oct nov dec".split(),
                     range(1, 13)))
ENGLISH_DATE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(\d{1,2}),?\s+(20\d{2})\b", re.I
)
# The URL itself is an exact existing public source, NOT user-provided input.
# The venue / host pairing must also be known; generic pages are excluded.
SOURCES = {
    "le-rex-toulouse": ("www.lerextoulouse.com", re.compile(
        r"/fr/programmation/[a-z0-9-]+/?", re.I), "rex"),
    "le-ferrailleur-nantes": ("www.leferrailleur.fr", re.compile(
        r"/evenement/[a-z0-9-]+/\d+/?", re.I), "ferrailleur"),
    "jokers-pub-angers": ("www.jokerspubangers.com", re.compile(
        r"/jokers-concert-programmation-[a-z0-9+_.-]+\.html", re.I), "jokers"),
    # Whitelisted five exactly reviewed first-party Vauréal concert pages.
    # Never treat a generic venue agenda as a published concert status.
    "le-forum-vaureal": ("leforum.cergypontoise.fr", re.compile(
        r"/agenda/[a-z0-9-]+", re.I), "forum"),
    "le-brin-de-zinc-barberaz": ("www.billetweb.fr", re.compile(
        r"/[a-z0-9-]+", re.I), "brin"),
    "bonjour-minuit-saint-brieuc": (
        "bonjour-minuit.fr",
        re.compile(r"/evenement/(?:magma-02dec26|sbrbs-30janv27)/", re.I),
        "bonjour"),

    # First pilot for already published Rocher bills; exact official detail
    # only. Other Rocher dates still require separate lineup qualification.
    "le-rocher-de-palmer-cenon": (
        "lerocherdepalmer.fr", re.compile(r"/agenda/gwendoline"), "rocher"),
    # Glazart pages are first-party dated concert details, NOT agenda cards.
    "glazart-paris": (glazart_adapter.HOST, glazart_adapter.DETAIL, "glazart"),
    "le-trabendo-paris": (trabendo_adapter.HOST, trabendo_adapter.DETAIL, "trabendo"),
    "la-maroquinerie-paris": (
        maroquinerie_adapter.HOST,
        re.compile(r"/fr/agenda/view/(?:2212/allt|2180/horskh)/",re.I),
        "maroquinerie"),
    "la-boule-noire-paris": (
        boule_noire_adapter.HOST,
        re.compile(r"/ice-sealed-eyes/",re.I),
        "boule-noire"),
}
BONJOUR_WATCH_URLS = {
    "go-c-20261202-saint-brieuc-magma":
        "https://bonjour-minuit.fr/evenement/magma-02dec26/",
    "go-c-20270130-saint-brieuc-sbrbs":
        "https://bonjour-minuit.fr/evenement/sbrbs-30janv27/",
}
BONJOUR_HEADLINES = {
    "go-c-20261202-saint-brieuc-magma": "Magma",
    "go-c-20270130-saint-brieuc-sbrbs":
        "SBRBS release party Atoem Sarakiniko DJ Cup of Tea",
}

FORUM_WATCH_URLS = {
    "go-c-20261106-vaureal-senser-psykup":
        "https://leforum.cergypontoise.fr/agenda/senser",
    "go-c-20261107-vaureal-wolves-throne-room":
        "https://leforum.cergypontoise.fr/agenda/wolves-throne-room",
    "go-c-20261112-vaureal-mass-hysteria":
        "https://leforum.cergypontoise.fr/agenda/mass-hysteria",
    "go-c-20270317-vaureal-michael-schenker-group":
        "https://leforum.cergypontoise.fr/agenda/michael-schenker-group",
    "go-c-20270522-vaureal-hard-rock-party":
        "https://leforum.cergypontoise.fr/agenda/hard-rock-party",
}
FORUM_MONTHS = dict(zip(
    "janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre".split(),
    range(1,13)
))
FORUM_FULL_DATE = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d{2})\b"
)
FORUM_STATUS = re.compile(r"\b(annule|annulee|annulation|reporte|reportee|"
                          r"deplace|deplacee|cancelled|postponed)\b")

TRABENDO_EXACT_TWO_BILLS = {
    # Individually reviewed PUBLIC concert IDs and their exact official URLs.
    # This is a watchdog proof rule only; it CANNOT approve or publish anything.
    "go-c-20261112-paris-frankie-witch-fingers": {
        "url": "https://www.letrabendo.net/programmation/frankie-and-the-witch-fingers/",
        "date": "2026-11-12",
        "names": ("Frankie and the Witch Fingers", "Iguana Death Cult"),
    },
    "go-c-20261128-paris-kid-kapichi": {
        "url": "https://www.letrabendo.net/programmation/kid-kapichi/",
        "date": "2026-11-28",
        "names": ("Kid Kapichi", "Demob Happy"),
    },
}
TRABENDO_FRENCH_MONTHS = (
    "", "janvier", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
)

CHECK_LIMIT = 24


def norm(value):
    # NFKD MUST precede casefold: official websites sometimes use
    # mathematical bold glyphs like 𝗦𝗽𝗲𝗰𝗶𝗮𝗹 𝗚𝘂𝗲𝘀𝘁.
    # Casefolding first drops their uppercase Latin equivalents later.
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+",
                               text.encode("ascii", "ignore").decode("ascii")))


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_title = 0
        self.hidden = 0
        self.title = []
        self.body = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        if tag == "title":
            self.in_title += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1
        if tag == "title":
            self.in_title = max(0, self.in_title - 1)

    def handle_data(self, data):
        if self.in_title and data.strip():
            self.title.append(" ".join(data.split()))
        if not self.hidden and not self.in_title and data.strip():
            self.body.append(" ".join(data.split()))


def source_kind(event):
    url = event.get("officialUrl")
    spec = SOURCES.get(event.get("venueId"))
    if not spec or not isinstance(url, str):
        return None
    target = urlsplit(url)
    hostname, pattern, kind = spec
    if (target.scheme != "https" or target.hostname != hostname
            or target.username or target.password or target.port
            or (target.query and kind != "maroquinerie")
            or target.fragment or not pattern.fullmatch(target.path)):
        return None
    # Do not mistake the generic Billetweb listing for an individual page.
    if kind == "brin" and target.path == "/multi_event.php":
        return None
    if kind == "forum" and FORUM_WATCH_URLS.get(event.get("id")) != url:
        return None
    if kind == "bonjour" and BONJOUR_WATCH_URLS.get(event.get("id")) != url:
        return None
    if kind == "rocher" and event.get("id") != "go-c-20261107-cenon-gwendoline":
        return None
    if kind == "glazart" and glazart_adapter.event_date(url) is None:
        return None
    if kind == "trabendo" and not trabendo_adapter.safe(url):
        return None
    if kind == "maroquinerie" and url not in (
            "https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7",
            "https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=18"):
        return None
    if kind == "boule-noire" and url != "https://laboule-noire.fr/ice-sealed-eyes/":
        return None
    return kind


def eligible(catalogue, today):
    return [
        e for e in catalogue["events"]
        if isinstance(e.get("date"), str) and
        today <= dt.date.fromisoformat(e["date"]) and
        source_kind(e) is not None
    ]


def choose(catalogue, today, limit=CHECK_LIMIT):
    """Near-term first, deterministic rotation for the distant events."""
    if not 1 <= limit <= 40:
        raise ValueError("Unreasonable daily source cap")
    options = eligible(catalogue, today)
    near = sorted(
        (e for e in options if dt.date.fromisoformat(e["date"]) <=
         today + dt.timedelta(days=14)),
        key=lambda e: (e["date"], e["id"])
    )
    if len(near) >= limit:
        # Never skip the soonest concert merely because rotation advanced.
        # Later dates will rise in priority once the earlier gigs have passed.
        return near[:limit], len(options)
    far = sorted(
        (e for e in options if e not in near),
        key=lambda e: (e["date"], e["id"])
    )
    remaining = limit - len(near)
    if not far:
        return near, len(options)
    offset = (today.toordinal() * remaining) % len(far)
    return near + [far[(offset + i) % len(far)]
                   for i in range(min(remaining, len(far)))], len(options)


def brin_detail(page):
    parsed = VisibleText()
    parsed.feed(page)
    title = " ".join(parsed.title)
    body = " ".join(parsed.body)
    if "Le Brin de Zinc" not in body:
        raise ValueError("Nom du lieu absent de la billetterie individuelle")
    dates = set()
    for m in ENGLISH_DATE.finditer(body):
        try:
            dates.add(dt.date(int(m[3]), MONTHS_EN[m[1].lower()],
                              int(m[2])).isoformat())
        except ValueError:
            continue
    if len(dates) != 1:
        raise ValueError("Date de billetterie unique absente ou ambiguë")
    if not title.lower().startswith(("tickets :", "billets :", "tickets -")):
        raise ValueError("Titre de billetterie non reconnu")
    return {"date": dates.pop(), "title": title.split(":", 1)[-1].strip()}


def jokers_detail(page):
    """Only the named acts of a first-party individual gig; no date inference."""
    parsed = VisibleText()
    parsed.feed(page)
    text = " ".join(parsed.body)
    if len(text) < 80 or not parsed.title and not text:
        raise ValueError("Page Joker vide ou partielle")
    return norm(text)


def jokers_lineup(event, page, artists):
    """Check explicit H1 section headings, not mere biography mentions."""
    class Headings(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_heading = False
            self.buffer = []
            self.items = []
        def handle_starttag(self, tag, attrs):
            if tag in ("h1","h2"):
                self.in_heading = tag
                self.buffer = []
        def handle_endtag(self, tag):
            if tag == self.in_heading:
                self.items.append(norm(" ".join(self.buffer)))
                self.in_heading = False
        def handle_data(self, value):
            if self.in_heading:
                self.buffer.append(value)
    doc=Headings()
    doc.feed(page)
    expected=[norm(artists.get(x,"")) for x in event["artistIds"]]
    if not all(expected):
        raise ValueError("Artiste sans nom dans le catalogue")
    if not doc.items:
        raise ValueError("En-tête de programmation du Joker absent")
    return all(name in doc.items for name in expected)


def forum_inspect(event, page, artists):
    """Compare only the named event header of an exact Forum first-party page.

    Never infer a show's date from unrelated biographies, footer years or
    recommended events. If the date is absent, an exact lineup check may
    return "lineup_only" but NEVER "matched".
    """
    doc=club_pages.MainText()
    doc.feed(page)
    headers=[(i,norm(value)) for i,(tag,value) in enumerate(doc.records)
             if tag=="h1"]
    if len(headers)!=1:
        return {"status":"unverifiable","reason":"En-tête du concert du Forum absent"}
    pos,head=headers[0]
    names=[norm(artists.get(aid,"")) for aid in event.get("artistIds",[])]
    if not names or not all(names):
        return {"status":"unverifiable","reason":"Noms d'artistes manquants du catalogue"}
    body=doc.records[pos+1:]
    subtitles=[]
    for tag,raw in body:
        val=norm(raw)
        if "production le forum" in val:
            break
        if tag=="p" and val:
            subtitles.append(val)
    if event["id"]=="go-c-20270522-vaureal-hard-rock-party":
        lineup_match=(head=="hard rock party" and
                      norm(" ".join(subtitles[:1]))==norm(" ".join(names)))
    elif event["id"]=="go-c-20270317-vaureal-michael-schenker-group":
        lineup_match=head.endswith(names[0]) and "tour 2027" in head
    else:
        lineup_match=(head==names[0] and
                      (len(names)==1 or
                       bool(subtitles) and subtitles[0]==norm(" ".join(names[1:]))))
    if not lineup_match:
        return {"status":"lineup_review",
                "reason":"Noms de l'affiche principale et premières parties à recouper"}
    visible=VisibleText()
    visible.feed(page)
    plain=norm(" ".join(visible.body))
    start=plain.find(head)
    if start<0:
        return {"status":"unverifiable","reason":"Texte officiel de concert incomplet"}
    header=plain[start+len(head):start+len(head)+420]
    header=header.split("production le forum",1)[0]
    if FORUM_STATUS.search(header):
        return {"status":"content_review",
                "reason":"Indice de report/annulation/déplacement : vérification humaine nécessaire"}
    dates=set()
    for match in FORUM_FULL_DATE.finditer(header):
        try:
            dates.add(dt.date(int(match[3]),FORUM_MONTHS[match[2]],
                              int(match[1])).isoformat())
        except ValueError:
            continue
    if len(dates)>1:
        return {"status":"unverifiable",
                "reason":"Plusieurs dates complètes dans l'en-tête officiel"}
    if not dates:
        return {"status":"lineup_only",
                "reason":"Artistes sur l'affiche officielle ; année et date non revérifiées"}
    found=next(iter(dates))
    if found!=event["date"]:
        return {"status":"date_review","observedDate":found,
                "reason":"Date officielle différente : revue humaine nécessaire"}
    # Source does not certify a precise show start here. Wolves' official
    # page even has conflicting reported times: do not assert one.
    return {"status":"date_only","observedDate":found,
            "reason":"Date et affiche principale corroborées ; horaire et statut non inférés"}


def bonjour_inspect(event, page, artists):
    """First-party event date/room/lineup, no automatic publication."""
    parsed=bonjour_minuit_adapter.Detail()
    parsed.feed(page)
    nodes=parsed.nodes
    heads=[i for i,(tag,_) in enumerate(nodes) if tag=="h1"]
    if len(heads)!=1:
        return {"status":"unverifiable","reason":"En-tête officiel absent"}
    i=heads[0]
    if norm(nodes[i][1])!=norm(BONJOUR_HEADLINES[event["id"]]):
        return {"status":"lineup_review",
                "reason":"En-tête nominatif différent : revue indépendante"}
    # Real pages encode date / venue in DIV/SPAN, not in P. Restrict to
    # visible fields between this H1 and the first named artist H2.
    header=bonjour_minuit_adapter.plain(" ".join(parsed.header_chunks))
    early=re.split(r"\b(?:tarifs|placement|si vous aimez|billetterie)\b",
                   header,maxsplit=1)[0][:1200]
    dates=bonjour_minuit_adapter.full_dates(early)
    if len(dates)!=1:
        return {"status":"unverifiable","reason":"Année complète absente"}
    day=next(iter(dates))
    if "grande salle" not in early:
        return {"status":"content_review","observedDate":day,
                "reason":"Changement possible d'espace musical ; revue seulement"}
    if bonjour_minuit_adapter.CANCEL.search(early):
        return {"status":"content_review","observedDate":day,
                "observedSourceStatus":"cancelled_notice",
                "reason":"Annulation explicitement mentionnée ; preuve à recouper"}
    if bonjour_minuit_adapter.POSTPONE.search(early):
        return {"status":"content_review","observedDate":day,
                "observedSourceStatus":"postponement_notice",
                "reason":"Report explicitement mentionné ; preuve à recouper"}
    if bonjour_minuit_adapter.SOLD_OUT.search(early):
        return {"status":"content_review","observedDate":day,
                "observedSourceStatus":"sold_out_notice",
                "reason":"Complet annoncé : ceci n'est PAS une annulation"}
    if day!=event["date"]:
        return {"status":"date_review","observedDate":day,
                "reason":"Date officielle différente ; aucune modification automatique"}
    first_h2=next((n for n in range(i+1,len(nodes))
                   if nodes[n][0]=="h2"),None)
    if first_h2 is None:
        return {"status":"unverifiable","reason":"Artistes officiels absents"}
    expected=[norm(artists.get(aid,"")) for aid in event["artistIds"]]
    if not expected or not all(expected):
        return {"status":"unverifiable","reason":"Identité d'artiste absente du catalogue"}
    actual=[re.sub(r"\s+release party$","",norm(x))
            for tag,x in nodes[i+1:] if tag=="h2"]
    if actual[:len(expected)]!=expected:
        return {"status":"lineup_review","observedDate":day,
                "reason":"Artistes officiels différents : revue obligatoire"}
    # Genre is the named lead act's adjacent badge, never bio or menu.
    style=bonjour_minuit_adapter.plain(
        " ".join(parsed.first_style_chunks))[:95]
    if (not style and first_h2+1<len(nodes)
            and nodes[first_h2+1][0]=="p"
            and len(nodes[first_h2+1][1])<=85):
        style=bonjour_minuit_adapter.plain(nodes[first_h2+1][1])
    found=bonjour_minuit_adapter.STYLE.search(style)
    if not found or found.start()!=0:
        return {"status":"unverifiable",
                "reason":"Badge de genre pertinent non vérifiable"}
    # Door clocks and tentative show times never prove a music-start hour.
    return {"status":"matched","observedDate":day,
            "reason":"Date, salle et artistes vérifiés ; début musical NON vérifié"}




def rocher_inspect(event, page, artists):
    """Audit exact Gwendoline bill from the first-party named event article.

    Do not infer a cancellation from broken HTML. A different named support
    is an actionable review alert, NEVER an automatic overwrite.
    """
    row=rocher_palmer_adapter.parse_detail(page)
    if (len(row["name"])!=1 or len(set(row["dates"]))!=1 or
            len(row["venue"])!=1 or
            not rocher_palmer_adapter.norm(row["venue"][0]).startswith(
                "le rocher de palmer")):
        return {"status":"unverifiable",
                "reason":"Fiche Rocher sans événement, date et salle uniques"}
    if rocher_palmer_adapter.BLOCK.search(norm(" ".join(row["label"]))):
        return {"status":"content_review",
                "reason":"Statut officiel à recontrôler (report, annulation ou hors les murs)"}
    date=next(iter(set(row["dates"]))).isoformat()
    if date!=event["date"]:
        return {"status":"date_review","observedDate":date,
                "reason":"Date du concert modifiée sur la fiche officielle"}
    try:
        bill,named=rocher_palmer_adapter.official_bill(
            row,{"name":event["title"]})
    except (ValueError,IndexError,KeyError) as exc:
        return {"status":"unverifiable",
                "reason":"Plateau nominatif officiel indéterminable : " + str(exc)[:100]}
    expected=[norm(artists.get(i,"")) for i in event.get("artistIds",[])]
    observed=[norm(x) for x in named]
    if not expected or not all(expected):
        return {"status":"unverifiable",
                "reason":"Artiste publié absent du catalogue"}
    if observed!=expected:
        return {"status":"lineup_review","observedDate":date,
                "observedArtists":named,
                "reason":"Programmation officielle différente du catalogue, premières parties à corriger après revue"}
    # Check start time only when the catalogue *already* claims it is a
    # musical start. Never conflate the separate door-opening timestamp.
    if event.get("timeMeaning")=="début du concert" and event.get("time"):
        m=re.findall(
            r"\bdebut (?:du|des|de) concerts?\s*:\s*([01]\d|2[0-3]):([0-5]\d)\b",
            rocher_palmer_adapter.flat(" ".join(row["visible"])))
        if len(m)!=1:
            return {"status":"unverifiable",
                    "reason":"Heure de début musical non attestée sur la fiche"}
        observed_time=f"{m[0][0]}:{m[0][1]}"
        if observed_time!=event["time"]:
            return {"status":"time_review","observedDate":date,
                    "reason":"Début du concert différent sur la fiche officielle"}
    return {"status":"matched","observedDate":date}

def trabendo_exact_named_support(event, page, artists, detail):
    """Verify BOTH named acts in the same first-party concert card.

    Restrict to two individually signed public bills. The <title> and first
    dated genre card are checked separately by trabendo_adapter; this second
    check only accepts the exact lineup next to the SECOND event date, before
    door opening, and before any recommended event carousel. Artist bios and
    unrelated cards are NEVER accepted as evidence of a support band.
    """
    signed = TRABENDO_EXACT_TWO_BILLS.get(event.get("id"))
    if not signed or not isinstance(event.get("artistIds"), list):
        return False
    if (event.get("officialUrl") != signed["url"]
            or event.get("date") != signed["date"]
            or len(event["artistIds"]) != len(signed["names"])
            or not all(norm(artists.get(aid)) == norm(name)
                       for aid, name in zip(event["artistIds"], signed["names"]))
            or norm(event.get("title")) != norm(" + ".join(signed["names"]))
            or norm(detail.get("leadArtist")) != norm(signed["names"][0])
            or norm(detail.get("name")) != norm(signed["names"][0])
            or norm(detail.get("classification", [""])[0]) not in
                {norm(g) for g in event.get("genres", [])}):
        return False
    # Preserve '+' in the programme: using norm() here would erase the
    # explicit official support separator, a necessary proof of the lineup.
    doc = trabendo_adapter.Parser()
    doc.feed(page)
    raw = " ".join(doc.fragments)
    display = unicodedata.normalize("NFKD", raw).encode(
        "ascii", "ignore").decode("ascii").casefold()
    display = " ".join(display.split())
    display = display.split("vous devriez aimer", 1)[0]
    # Ignore all preceding biographies and generic genre categories.
    # The exact event summary card must precede the full named lineup.
    venue_cards = list(re.finditer(
        r"trabendo\s*-\s*salle\s+de\s+concert\b", display))
    if len(venue_cards) != 1:
        return False
    actual = display[venue_cards[0].end():]
    day = dt.date.fromisoformat(signed["date"])
    date_str = (str(day.day) + " " +
                TRABENDO_FRENCH_MONTHS[day.month] + " " + str(day.year))
    names = [norm(x) for x in signed["names"]]
    return bool(re.match(
        r"^\s*" + re.escape(date_str) + r"\s+" +
        re.escape(names[0]) + r"\s*\+\s*" +
        re.escape(names[1]) + r"\s+ouverture\s+des\s+portes\b",
        actual,
    ))


def inspect(event, page, artists):
    """Parse source-specific *positive evidence*. Never infer cancellation."""
    kind = source_kind(event)
    if kind is None:
        return {"status": "unsupported", "reason": "No trusted individual venue page"}
    try:
        if kind == "rocher":
            return rocher_inspect(event,page,artists)
        if kind == "bonjour":
            return bonjour_inspect(event,page,artists)
        if kind == "rex":
            evidence = official_recheck.parse_detail(page)
            observed_date = evidence["date"]
            source_title = evidence["title"]
            headline_match = norm(source_title) == norm(event["title"])
            lineup_match = headline_match
            if not headline_match:
                # Some first-party Rex H2s name only the headline. Accept an
                # added support act ONLY when it is explicitly named as
                # "Special Guest" on the same event page (not just mentioned
                # somewhere in a band's biography).
                names = [norm(artists.get(aid, "")) for aid in event["artistIds"]]
                if len(names) > 1 and all(names) and norm(source_title) == names[0]:
                    visible = VisibleText()
                    visible.feed(page)
                    words = norm(" ".join(visible.body))
                    lineup_match = all(
                        re.search(r"\bspecial guest " + re.escape(name) + r"\b",
                                  words) is not None for name in names[1:]
                    )
            start_changed = False
        elif kind == "ferrailleur":
            evidence = ferrailleur_official.extract(page)
            observed_date = evidence["date"]
            tokens = [norm(t) for t in evidence["lineupTokens"]]
            # The Ferrailleur's 12 Dec 2026 page contains a documented
            # typographical error in its concert heading ("Lost in Kiyv"),
            # while its own body explicitly names the act "Lost in Kyiv".
            # Correct only this exact event/source, never use fuzzy matches
            # for other concerts or silently ignore a missing support act.
            if (event.get("id") == "go-c-20261212-nantes-lost-in-kyiv"
                    and event.get("officialUrl") ==
                        "https://www.leferrailleur.fr/evenement/lost-in-kyiv/5307"
                    and "lost in kiyv" in tokens):
                tokens.append("lost in kyiv")
            artist_names = [norm(artists.get(aid, "")) for aid in event["artistIds"]]
            if not all(artist_names):
                raise ValueError("Artiste sans nom dans le catalogue")
            lineup_match = all(name in tokens for name in artist_names)
            start_changed = (event.get("time") is not None and
                             event.get("timeMeaning") == "début du concert" and
                             event["time"] != evidence["time"])
        elif kind == "jokers":
            jokers_detail(page)
            lineup_match = jokers_lineup(event, page, artists)
            # Joker gig detail pages do not necessarily expose a full date.
            # Checking the lineup does NOT validate the calendar date.
            return {"status": "lineup_only" if lineup_match else "lineup_review",
                    "reason": ("Artistes vérifiés sur la fiche individuelle ; "
                               "date non revérifiable depuis cette page"
                               if lineup_match else
                               "Titres d'artistes absents des en-têtes officiels ; revue nécessaire")}
        elif kind == "forum":
            return forum_inspect(event,page,artists)
        elif kind == "trabendo":
            # Only exact first-party single-artist concert pages are
            # eligible. A changed date is an alert, never auto-publication
            # or a claim of cancellation. Do not infer the door time.
            source={"name":"Le Trabendo","city":"Paris",
                    "url":"https://www.letrabendo.net/programmation/"}
            try:
                # Allow a moved date earlier than the originally published
                # one to be parsed; the generic date comparison below
                # decides whether it requires an independent human review.
                detail=trabendo_adapter.detail_candidate(
                    page,event["officialUrl"],source,"2000-01-01")
            except ValueError:
                parsed=trabendo_adapter.Parser()
                parsed.feed(page)
                primary=trabendo_adapter.norm(
                    " ".join(parsed.fragments)).split("vous devriez aimer",1)[0]
                if trabendo_adapter.CANCEL.search(primary):
                    return {"status":"content_review",
                            "reason":"Indice de report, annulation ou changement sur la page officielle ; revue nécessaire"}
                raise
            observed_date=detail["date"]
            names=[norm(artists.get(aid,"")) for aid in event["artistIds"]]
            lineup_match=(
                (len(names)==1 and bool(names[0]) and
                 norm(detail["leadArtist"])==names[0] and
                 norm(detail["name"])==norm(event["title"]) and
                 norm(detail["classification"][0]) in
                 {norm(x) for x in event.get("genres",[])})
                or trabendo_exact_named_support(event, page, artists, detail)
            )
            start_changed=False
        elif kind == "maroquinerie":
            source={"name":"La Maroquinerie","city":"Paris",
                    "url":"https://www.lamaroquinerie.fr/fr/agenda/"}
            try:
                detail=maroquinerie_adapter.detail_candidate(
                    page,event["officialUrl"],source,"2000-01-01")
            except ValueError as exc:
                doc=maroquinerie_adapter.Visible()
                doc.feed(page)
                observed=norm(" ".join(doc.chunks))
                if maroquinerie_adapter.CANCEL.search(" ".join(doc.chunks)):
                    return {"status":"content_review",
                            "reason":"Indice de report ou changement de salle, relecture humaine exigée"}
                # Horskh's official detail names We Are Magonia, but omits
                # the year. The publication used an INDEPENDENT official
                # calendar cross-proof. Watching the detail ALONE must not
                # assert a date match or an event cancellation.
                if (event.get("id")=="go-c-20261121-paris-horskh"
                    and "Official full event date not proved" in str(exc)):
                    title=norm(" ".join(doc.titles))
                    names=[norm(artists.get(i,"")) for i in event["artistIds"]]
                    if (title==norm("HORSKH - La Maroquinerie - Agenda")
                        and len(names)==2 and names[0]=="horskh"
                        and names[1]=="we are magonia"
                        and re.search(r"\bpremiere partie\s+we are magonia\b",observed)):
                        return {"status":"lineup_only",
                                "reason":"Deux groupes visibles sur la fiche officielle ; année uniquement dans l'agenda distinct, date non revérifiée"}
                    return {"status":"lineup_review",
                            "reason":"Première partie ou titre officiel à recouper ; date non vérifiée"}
                raise
            primary=norm(artists.get(event["artistIds"][0],""))
            if not primary or norm(detail["leadArtist"])!=primary:
                return {"status":"lineup_review",
                        "reason":"Tête d’affiche non concordante sur la page officielle"}
            if detail["date"]!=event["date"]:
                return {"status":"date_review","observedDate":detail["date"],
                        "reason":"Date officielle différente ; revue humaine nécessaire"}
            return {"status":"date_only","observedDate":detail["date"],
                    "reason":"Date du concert sur fiche officielle ; programmation complète et horaires non revérifiés"}
        elif kind == "boule-noire":
            source={"name":"La Boule Noire","city":"Paris",
                    "url":"https://laboule-noire.fr/"}
            try:
                detail=boule_noire_adapter.detail_candidate(
                    page,event["officialUrl"],source,"2000-01-01")
            except ValueError:
                doc=boule_noire_adapter.Visible()
                doc.feed(page)
                if boule_noire_adapter.CANCEL.search(
                        boule_noire_adapter.norm(" ".join(doc.chunks))):
                    return {"status":"content_review",
                            "reason":"Indice de report ou annulation sur la fiche ; contrôle humain nécessaire"}
                raise
            first=norm(artists.get(event["artistIds"][0],""))
            if not first or norm(detail["leadArtist"])!=first:
                return {"status":"lineup_review",
                        "reason":"Artiste principal non confirmé par la salle"}
            if detail["date"]!=event["date"]:
                return {"status":"date_review","observedDate":detail["date"],
                        "reason":"Date officielle individuelle différente, revue humaine nécessaire"}
            return {"status":"date_only","observedDate":detail["date"],
                    "reason":"Date du concert recoupée entre formats ISO et français ; premières parties et horaires non revérifiés"}
        elif kind == "glazart":
            source = {"name": "Glazart", "city": "Paris",
                      "url": "https://www.glazart.com" + glazart_adapter.AGENDA}
            try:
                detail = glazart_adapter.detail_candidate(
                    page, event["officialUrl"], source, event["date"])
            except ValueError:
                # A disappearance, HTML redesign or missing proof is NOT a
                # cancellation. Only an explicit early first-party mention
                # gets a human-review alert; never a status change.
                parsed = glazart_adapter.Extract()
                parsed.feed(page)
                title = " ".join(parsed.title)
                early = " ".join(parsed.content[:45])[:350]
                if glazart_adapter.CANCEL.search(
                        glazart_adapter.normalize(title + " " + early)):
                    return {"status": "content_review",
                            "reason": "Mention possible d’annulation ou report sur la fiche officielle ; "
                                      "vérification humaine nécessaire, aucun statut déduit"}
                raise
            # Glazart abbreviates some headlines and the surrounding prose
            # cannot independently confirm every support act. A valid date
            # must NEVER be presented as a verified whole lineup.
            return {"status": "date_only", "observedDate": detail["date"],
                    "reason": "Date sur fiche individuelle vérifiée ; "
                              "programmation, genre et heure non revérifiés"}
        elif kind == "brin":
            evidence = brin_detail(page)
            observed_date = evidence["date"]
            headline = norm(evidence["title"])
            artist_names = [norm(artists.get(aid, "")) for aid in event["artistIds"]]
            if not all(artist_names):
                raise ValueError("Artiste sans nom dans le catalogue")
            lineup_match = all(name in headline for name in artist_names)
            start_changed = False  # A ticketing slot is not a concert start.
        else:
            raise ValueError("Source inconnue")
    except (ValueError, KeyError, IndexError, TypeError) as error:
        return {"status": "unverifiable", "reason": str(error)[:160]}
    if observed_date != event["date"]:
        return {"status": "date_review", "observedDate": observed_date,
                "reason": "Date officielle individuelle différente : revue nécessaire"}
    if not lineup_match:
        return {"status": "lineup_review",
                "reason": "Programmation ou titre à recouper manuellement"}
    if start_changed:
        return {"status": "time_review",
                "reason": "Heure de début officielle différente : revue nécessaire"}
    return {"status": "matched", "observedDate": observed_date}


def run(catalogue, today, limit=CHECK_LIMIT, fetch=None, robots=None):
    if not (isinstance(catalogue, dict) and catalogue.get("schemaVersion") == 1
            and catalogue.get("mode") == "preview-public-unlisted"
            and len(catalogue.get("events", [])) >= 127
            and len(catalogue.get("venues", [])) >= 53):
        raise ValueError("Cloud catalogue unexpected; refusing stale local fallback")
    events = catalogue["events"]
    ids = [e["id"] for e in events]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate published event IDs")
    selected, eligible_total = choose(catalogue, today, limit)
    lookup = {a["id"]: a["name"] for a in catalogue["artists"]}
    rows = []
    cache = {}
    fetch = fetch or (lambda url: discover.download(url, timeout=12, cap=550000))
    robots = robots or (lambda url, memo: discover.robots_allow(url, memo))
    for event in selected:
        url = event["officialUrl"]
        row = {"id": event["id"], "date": event["date"], "title": event["title"],
               "venueId": event["venueId"], "sourceUrl": url,
               "sourceType": source_kind(event)}
        try:
            if not robots(url, cache):
                row.update(status="source_unavailable", reason="Source interdite ou robots.txt indisponible")
            else:
                page, final = fetch(url)
                if not discover.same_host(final, url) or final.split("?", 1)[0] != url:
                    row.update(status="source_unavailable",
                               reason="Redirection vers une autre page; aucune inférence")
                else:
                    row.update(inspect(event, page, lookup))
        except Exception as exc:
            row.update(status="source_unavailable",
                       reason="Réseau ou document indisponible : " + type(exc).__name__)
        rows.append(row)
    from collections import Counter
    counts = Counter(r["status"] for r in rows)
    return {
        "schema": "grossesondes.concert.published-watch.v1",
        "checkedAt": today.isoformat(), "mode": "read-only",
        "catalogueEvents": len(events), "eligibleOfficialIndividual": eligible_total,
        "checked": len(rows), "otherNotAutomaticallyVerifiable":
            len(events) - eligible_total,
        "eligibleNotCheckedToday": eligible_total-len(rows),
        "counts": dict(counts), "rows": rows,
        "needsReview": [r for r in rows if r["status"] in
                        ("date_review", "lineup_review", "time_review", "content_review")],
        "publicationAllowed": False,
        "policy": "Aucune annulation, suppression ou modification automatique."
    }


def markdown(report):
    lines = [
        "## Concerts Grosses Ondes — suivi des fiches publiées",
        f"Date de contrôle : {report['checkedAt']} · lecture seule",
        f"Catalogue : {report['catalogueEvents']} concerts",
        f"Fiches individuelles de salle éligibles : {report['eligibleOfficialIndividual']}",
        f"Contrôlées ce passage : {report['checked']}",
        f"Non automatisables à ce stade : {report['otherNotAutomaticallyVerifiable']}",
        f"Éligibles non revues aujourd'hui : {report['eligibleNotCheckedToday']}",
    ]
    for label in ("matched", "date_only", "lineup_only", "date_review",
                  "lineup_review", "time_review", "content_review",
                  "unverifiable", "source_unavailable"):
        lines.append(f"- {label} : {report['counts'].get(label,0)}")
    if report["counts"].get("date_only"):
        lines.append("Concerts Glazart : date corroborée sur la fiche officielle ; "
                     "programmation, genre et heure NON confirmés par ce contrôle.")
    if report["counts"].get("lineup_only"):
        lines.append("Concerts Joker : artistes confirmés sur fiche individuelle, "
                     "mais date non revérifiée ; aucun constat de maintien de date.")
    if report["needsReview"]:
        lines.append("### Alertes à vérifier par relecture humaine/indépendante")
        for row in report["needsReview"]:
            lines.append(f"- {row['date']} — {row['title']} : {row['status']} ({row['sourceUrl']})")
    else:
        lines.append("Aucune divergence exploitable sur les fiches examinées.")
    lines.append(
        "**Aucun changement de concert / statut / billetterie n'est publié par cette surveillance.**"
    )
    return "\n".join(lines) + "\n"


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--catalogue", default=CLOUD)
    arg.add_argument("--report", required=True)
    arg.add_argument("--summary", required=True)
    arg.add_argument("--max-check", type=int, default=CHECK_LIMIT)
    args = arg.parse_args()
    if args.catalogue.startswith("https://"):
        if args.catalogue != CLOUD:
            raise ValueError("Only the official GitHub Pages cloud catalogue is supported")
        catalogue = discover.json_url(CLOUD)
    else:
        catalogue = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
    report = run(catalogue, discover.today_fr(), args.max_check)
    Path(args.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    Path(args.summary).write_text(markdown(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
          ("catalogueEvents", "eligibleOfficialIndividual", "checked", "counts")},
          ensure_ascii=False))


if __name__ == "__main__":
    main()
