"""Conservative multi-band Atabal verifier for a repeated first-party bill.

Unlike the narrow Peter Hook pilot, this is reusable *only* when an exact
Atabal individual event page explicitly repeats EVERY billed artist as a
named artist section. No biography, ticket time or slug can invent a band.
This module never writes approvals or public catalogue data.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import atabal_adapter as source

VENUE = "atabal-biarritz"
HOST = "www.atabal-biarritz.fr"
AGENDA = "https://www.atabal-biarritz.fr/agenda/concerts/"
STRUCTURE = "event-header-and-named-artist-sections"
BAD_HEADLINE = re.compile(
    r"\b(?:guest|special guest|surprise|tba|a confirmer|festival|"
    r"annule|annulee|reporte|reportee|cancelled|postponed)\b")
MAX_ACTS = 4


def slug(name):
    return source.norm(name).replace(" ", "-")[:72].strip("-")


class FirstArticleHeadings(HTMLParser):
    """Group complete headings, including text split across nested HTML tags.

    The discovery parser records text fragments separately; that is useful
    for broad intake but cannot safely identify a multi-artist H2 assembled
    from spans, <strong> and <br> in a live venue's event template.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.done = False
        self.hidden = 0
        self.capture = None
        self.buffer = []
        self.h1 = []
        self.h2 = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "article" and not self.in_article:
            self.in_article = True
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        if self.in_article and not self.hidden and self.capture is None:
            if tag in ("h1", "h2", "h4"):
                self.capture = tag
                self.buffer = []

    def handle_data(self, data):
        if self.in_article and not self.done and not self.hidden:
            if self.capture is not None:
                self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1
            return
        if not self.in_article or self.done:
            return
        if self.capture == tag:
            # Do not insert spaces between inline styling fragments: that
            # would transform "Kill!<span>Kill!</span>Diana" into another act.
            heading = " ".join("".join(self.buffer).split())
            if tag == "h4" and source.norm(heading).startswith("vous devriez aimer"):
                self.done = True
            elif tag == "h1":
                self.h1.append(heading)
            elif tag == "h2":
                self.h2.append(heading)
            self.capture = None
            self.buffer = []
        if tag == "article":
            self.done = True


def exact_names(page):
    p = FirstArticleHeadings()
    p.feed(page)
    if len(p.h1) != 1 or not p.h1[0]:
        raise ValueError("Atabal: titre principal absent ou incomplet")
    lead = p.h1[0]
    h2 = p.h2
    if not h2 or not re.search(r"\s+~\s+", h2[0]):
        raise ValueError("Atabal: plateau multi-artistes explicite absent")
    supporting = [x.strip() for x in re.split(r"\s+~\s+", h2[0])]
    names = [lead] + supporting
    if not 3 <= len(names) <= MAX_ACTS:
        raise ValueError("Atabal: nombre de groupes non pris en charge")
    normalized = [source.norm(n) for n in names]
    if (any(len(n) < 3 for n in normalized)
            or len(set(normalized)) != len(names)
            or any(BAD_HEADLINE.search(n) for n in normalized)):
        raise ValueError("Atabal: artiste ambigu, invité ou festival")
    # Repeated named artist sections are independent of the header spelling.
    sections = [source.norm(n) for n in h2[1:]]
    if not sections or any(n not in normalized for n in sections):
        raise ValueError("Atabal: section artiste étrangère à l'affiche")
    if set(sections) != set(normalized):
        raise ValueError("Atabal: artiste non confirmé dans sa propre section")
    return names


def verify(candidate, page, catalogue, today):
    if (candidate.get("source") != "agenda_officiel_atabal_detail"
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Atabal: candidat non qualifié ou doublon")
    if (source.norm(candidate.get("venue")) != "atabal"
            or source.norm(candidate.get("city")) != "biarritz"
            or candidate.get("venueCatalogueId") != VENUE):
        raise ValueError("Atabal: identité de salle incohérente")
    url = candidate.get("sourceUrl", "")
    if not isinstance(url, str) or source.link_ok(url) != url:
        raise ValueError("Atabal: URL officielle individuelle stricte exigée")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOST
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment):
        raise ValueError("Atabal: domaine non autorisé")
    d = source.slug_day(url)
    if d is None or d.isoformat() != candidate.get("date") or d <= today:
        raise ValueError("Atabal: date URL, veille ou futur incohérents")
    # Use the original discovery parser as a second check on the live HTML:
    # first visible event date, cancellation, off-site venue and official h5.
    src = {"name": "Atabal", "city": "Biarritz", "department": "64",
           "url": AGENDA}
    card = {"date": d.isoformat(),
            "slug": parsed.path.split("/")[-2], "url": url}
    fresh = source.candidate(page, url, card, src, today.isoformat())
    if (source.norm(fresh["name"]) != source.norm(candidate.get("name"))
            or fresh["date"] != candidate.get("date")
            or fresh["classification"] != candidate.get("classification")):
        raise ValueError("Atabal: titre, date ou genre modifié depuis la découverte")
    names = exact_names(page)
    if source.norm(names[0]) != source.norm(fresh["name"]):
        raise ValueError("Atabal: tête d'affiche incohérente")
    venues = [v for v in catalogue.get("venues", [])
              if v.get("id") == VENUE]
    if len(venues) != 1 or source.norm(venues[0].get("city")) != "biarritz":
        raise ValueError("Atabal: lieu non validé dans le catalogue")
    artists = catalogue.get("artists", [])
    index = {}
    reserved_ids = set()
    for row in artists:
        reserved_ids.add(row["id"])
        keys = [row.get("name")] + list(row.get("aliases") or [])
        for key in keys:
            if isinstance(key, str):
                index.setdefault(source.norm(key), set()).add(row["id"])
    ids, new_artists = [], []
    for name in names:
        known_ids = index.get(source.norm(name), set())
        if len(known_ids) > 1:
            raise ValueError("Atabal: alias d'artiste ambigu")
        if known_ids:
            aid = next(iter(known_ids))
            # Alias is not evidence of how to display the canonical artist.
            canonical = next(a for a in artists if a["id"] == aid)
            if source.norm(canonical["name"]) != source.norm(name):
                raise ValueError("Atabal: nom d'artiste alias non canonique")
        else:
            aid = slug(name)
            if not aid or aid in reserved_ids:
                raise ValueError("Atabal: collision d'identifiant artiste")
            new_artists.append({"id": aid, "name": name})
            reserved_ids.add(aid)
        ids.append(aid)
    if len(set(ids)) != len(ids):
        raise ValueError("Atabal: groupes ou identifiants en doublon")
    event_id = ("go-c-" + d.strftime("%Y%m%d") +
                "-biarritz-" + "-".join(slug(n) for n in names))
    if len(event_id) > 150:
        raise ValueError("Atabal: identifiant concert trop long")
    if any(e.get("id") == event_id or
           (e.get("date") == d.isoformat() and e.get("venueId") == VENUE
            and set(e.get("artistIds", [])) & set(ids)) or
           e.get("officialUrl") == url
           for e in catalogue.get("events", [])):
        raise ValueError("Atabal: affiche déjà enregistrée")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": names,
            "verifiedNewArtists": [a["name"] for a in new_artists],
            "sourceStructure": STRUCTURE,
            "notes": "En-tête multi-artistes et chaque section nominative relus; heure de début inconnue."
        }],
        "event": {
            "id": event_id, "title": " + ".join(names),
            "date": d.isoformat(), "time": None, "artistIds": ids,
            "venueId": VENUE, "genres": fresh["classification"],
            "status": "confirmed", "officialUrl": url,
            "sourceType": "salle", "organizer": "Atabal"
        },
        "newArtists": new_artists
    }
