"""Independent, fail-closed BBC concert recheck (no publication or network).

A first-party detail page must retain its discovery identity and corroborate
each billed performer in an individual visible event paragraph.  A title,
recommendation or artist biography on another page is never sufficient.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re

import bbc_adapter as adapter
import triage

SOURCE = "bbc_official_detail_review"
VENUE = "big-band-cafe-herouville"
STRUCTURE = "bbc-first-party-named-paragraphs"
UNSAFE = re.compile(
    r"\b(?:annul(?:e|ee|ation)|reporte(?:e)?|postponed|cancelled|"
    r"festival|hommage|tribute|cover(?:s)?|tba|surprise|guest|invite)\b")
# An artist biography may mention an album 'tribute' or festivals played
# elsewhere. Reject actual cancellation/postponement markers, not biographies.
BODY_UNSAFE = re.compile(
    r"\b(?:annul(?:e|ee|ation)|reporte(?:e)?|postponed|cancelled)\b")
UNANNOUNCED = frozenset({
    "guest", "special guest", "premiere partie", "1ere partie",
    "1re partie", "support", "a confirmer", "tba", "surprise",
    "invite surprise", "artiste surprise",
})
GENRES = frozenset({
    "rock", "hard rock", "punk", "punk rock", "hardcore", "metal",
    "metal alternatif", "heavy metal", "death metal", "black metal",
    "stoner", "doom", "sludge", "garage", "garage rock", "noise", "post rock"
})


class EventParagraphs(HTMLParser):
    """Read paragraphs from the first official event section only."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entered = False
        self.finished = False
        self.depth = 0
        self.hidden = 0
        self.p_depth = 0
        self.buffer = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if self.finished:
            return
        if tag in adapter.SKIP:
            self.hidden += 1
        if tag == "section" and not self.hidden:
            if not self.entered:
                self.entered = True
            self.depth += 1
        if self.entered and not self.hidden and tag == "p":
            if self.p_depth == 0:
                self.buffer = []
            self.p_depth += 1

    def handle_data(self, data):
        if self.entered and not self.hidden and self.p_depth:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag in adapter.SKIP and self.hidden:
            self.hidden -= 1
            return
        if self.finished or not self.entered or self.hidden:
            return
        if tag == "p" and self.p_depth:
            self.p_depth -= 1
            if self.p_depth == 0:
                text = " ".join("".join(self.buffer).split())
                if text:
                    self.paragraphs.append(text)
        if tag == "section":
            self.depth -= 1
            if self.depth <= 0:
                self.finished = True


def artist_parts(title, catalogue):
    """Canonical acts only; unannounced guests are never inferred as artists."""
    parts = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    if parts:
        parts[-1] = re.sub(r"\s+\(LIVE\)$", "", parts[-1], flags=re.I).strip()
    guest = None
    if len(parts) > 1 and triage.words(parts[-1]) in UNANNOUNCED:
        guest = triage.words(parts.pop())
    # Some first-party bills stage a KNOWN artist as "X FAMILY & FRIENDS":
    # this is not a separate group. Keep X only when already canonical and
    # separately named in the first-party event description; named supports
    # after the plus sign remain mandatory and independently corroborated.
    collective = None
    for i, name in enumerate(parts):
        match = re.fullmatch(
            r"(.+?)\s+(?:FAMILY\s*&\s*FRIENDS|&\s*FRIENDS)",
            name, flags=re.I)
        if match:
            base = match.group(1).strip()
            known = [a for a in catalogue.get("artists", [])
                     if triage.words(a.get("name")) == triage.words(base)]
            if (collective is not None or len(known) != 1
                    or not known[0].get("id")):
                raise ValueError("BBC : collectif sans artiste canonique")
            collective = {"artistName": base,
                          "nonNominativeLabel": "family-and-friends"}
            parts[i] = base
    keys = [triage.words(p) for p in parts]
    if (not parts or any(not 3 <= len(key) <= 100 or key in UNANNOUNCED
                         or UNSAFE.search(key) for key in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError("BBC : programmation ou noms d'artistes ambigus")
    return parts, guest, collective


def verify(candidate, page, catalogue, today):
    if not isinstance(candidate, dict) or not isinstance(today, dt.date):
        raise ValueError("BBC : candidate ou date invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("officialDetailFound") is not True
            or candidate.get("sourcePage") != adapter.AGENDA
            or candidate.get("venue") != "Big Band Café"
            or candidate.get("city") != "Hérouville-Saint-Clair"
            or str(candidate.get("department")) != "14"):
        raise ValueError("BBC : identité, stabilité ou quarantaine incompatibles")
    url = candidate.get("sourceUrl")
    if not isinstance(url, str) or adapter.event_url(url) != url:
        raise ValueError("BBC : URL individuelle officielle obligatoire")
    if not isinstance(page, str) or not 100 <= len(page) <= 500_000:
        raise ValueError("BBC : fiche officielle absente ou illisible")
    source = {"name": "Big Band Café", "city": "Hérouville-Saint-Clair",
              "department": "14", "url": adapter.AGENDA}
    fresh = adapter.candidate(page, url, source, today.isoformat())
    for key in ("source", "sourceUrl", "sourcePage", "name", "leadArtist",
                "date", "classification", "venue", "city", "department",
                "officialDetailFound"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("BBC : fiche modifiée depuis la découverte : " + key)
    if (dt.date.fromisoformat(fresh["date"]) <= today
            or fresh.get("localTime") is not None):
        raise ValueError("BBC : date passée ou début musical non corroboré")
    if (len(fresh["classification"]) != 1
            or triage.words(fresh["classification"][0]) not in GENRES):
        raise ValueError("BBC : genre non corroboré")
    if not isinstance(catalogue, dict) or any(
            not isinstance(catalogue.get(k), list)
            for k in ("artists", "venues", "events")):
        raise ValueError("BBC : catalogue invalide")
    names, guest, collective = artist_parts(fresh["name"], catalogue)
    if triage.words(names[0]) != triage.words(fresh["leadArtist"]):
        raise ValueError("BBC : tête d'affiche non concordante")
    doc = EventParagraphs()
    doc.feed(page)
    if not doc.finished or not doc.paragraphs:
        raise ValueError("BBC : section de description officielle absente")
    # Each name must be explicitly printed in the current event's paragraphs.
    # The H1, ticket links, navigation and recommended acts never count.
    paragraphs = [triage.words(p) for p in doc.paragraphs]
    for name in names:
        token = triage.words(name)
        if not any(re.search(r"(?<![a-z0-9])" + re.escape(token)
                             + r"(?![a-z0-9])", p) for p in paragraphs):
            raise ValueError("BBC : artiste non corroboré dans sa description")
    if BODY_UNSAFE.search(" ".join(paragraphs)):
        raise ValueError("BBC : annonce ambiguë, report ou annulation")
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE]
    if (len(venues) != 1 or triage.words(venues[0].get("city")) !=
            "herouville saint clair" or any(venues[0].get(k) is None
            for k in ("latitude", "longitude"))):
        raise ValueError("BBC : salle ou coordonnées non confirmées")
    by_name, aliases, reserved = {}, set(), set()
    for row in catalogue["artists"]:
        reserved.add(row["id"])
        by_name.setdefault(triage.words(row.get("name")), []).append(row)
        aliases.update(triage.words(a) for a in (row.get("aliases") or [])
                       if isinstance(a, str))
    ids, new = [], []
    for name in names:
        key = triage.words(name)
        matches = by_name.get(key, [])
        if len(matches) > 1:
            raise ValueError("BBC : identité canonique multiple")
        if matches:
            aid = matches[0]["id"]
        else:
            if key in aliases:
                raise ValueError("BBC : alias préexistant, revue nécessaire")
            aid = key.replace(" ", "-")[:90].strip("-")
            if not 3 <= len(aid) <= 100 or aid in reserved:
                raise ValueError("BBC : identité d'artiste nouvelle ambiguë")
            new.append({"id": aid, "name": name})
            reserved.add(aid)
        ids.append(aid)
    if len(set(ids)) != len(ids):
        raise ValueError("BBC : artiste répété dans le programme")
    if any(e.get("officialUrl") == url or (
            e.get("date") == fresh["date"] and e.get("venueId") == VENUE
            and set(e.get("artistIds") or []) & set(ids))
            for e in catalogue["events"]):
        raise ValueError("BBC : concert déjà publié")
    event_id = ("go-c-" + fresh["date"].replace("-", "") +
                "-herouville-" + ids[0])
    if len(event_id) > 150 or any(e.get("id") == event_id
                                  for e in catalogue["events"]):
        raise ValueError("BBC : collision d'identifiant")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "sourceStructure": STRUCTURE,
            "officialArtistNames": names,
            "verifiedNewArtists": [x["name"] for x in new],
            **({"unannouncedSupportLabel": guest} if guest else {}),
            **({"nonNominativeCollectiveGuests": collective} if collective else {}),
        }],
        "event": {
            "id": event_id, "title": " + ".join(names),
            "date": fresh["date"], "time": None,
            "artistIds": ids, "venueId": VENUE,
            "genres": fresh["classification"], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "Big Band Café",
        },
        "newArtists": new,
    }
