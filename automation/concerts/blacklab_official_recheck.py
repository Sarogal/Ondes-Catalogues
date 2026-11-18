"""The Black Lab: source-wide, fail-closed first-party named-lineup verifier.

Read the official individual detail anew, require the headline AND its named
performance bill inside the early official detail body. Genres, biographies
and musical influences never create an artist. No per-concert allowlist or
arbitrary performer-count limit. The publisher separately checks all IDs.
"""
from __future__ import annotations

import datetime as dt
import re

import blacklab_adapter as adapter
import triage

SOURCE = "agenda_officiel_blacklab_detail_review"
VENUE_ID = "the-black-lab-wasquehal"
CITY = "wasquehal"
SOURCE_URL = adapter.AGENDA
STRUCTURE = "blacklab-first-party-named-bill-in-detail-v2"
NONCONCERT = re.compile(
    r"\b(?:festival|tribute fest|hommage|dj set|annule|reporte|"
    r"reportee|postponed|cancelled)\b")
UNNAMED = frozenset({
    "guest", "guests", "special guest", "special guests", "invite surprise",
    "premiere partie surprise", "support surprise", "surprise",
    "a confirmer", "tba",
})


def bill_from_official_body(title, chunks):
    """Corroborate EVERY billed musician in the official detail body.

    A title alone or artist-name mentions in a biography do not suffice:
    a multi-artist bill must be restated contiguously as a performance
    headline in an early official detail node. Single artists must likewise
    be repeated with a complete token boundary, not a similar spelling.
    """
    raw = re.split(r"\s+\+\s+", title)
    if not raw or any(not s.strip() for s in raw):
        raise ValueError("Black Lab : programme nominatif vide")
    guest = None
    if len(raw) > 1 and triage.words(raw[-1]) in UNNAMED:
        guest = triage.words(raw.pop())
    names = [" ".join(item.split()) for item in raw]
    normalized = [triage.words(name) for name in names]
    if (not names or any(
            not 3 <= len(name) <= 100 or
            not 3 <= len(key) <= 100 or key in UNNAMED
            for name,key in zip(names,normalized)) or
            len(set(normalized)) != len(normalized)):
        raise ValueError("Black Lab : identités d'artistes invalides")
    # The Black Lab's two reusable first-party formats:
    #  (1) the full "+-joined" bill is repeated at the START of a detail
    #      node, optionally followed by a musical style;
    #  (2) each exact artist gets its OWN separate early performer heading,
    #      in the same order as the H1. Biographical mentions do NOT count.
    # The evidence window scales with the number of billed performers;
    # this is not an artist-count ceiling or a list of approved concerts.
    body = [adapter.fold(value).strip()
            for value in chunks[:max(28,len(names)*8)]]
    label = adapter.fold(" + ".join(names))
    full_bill = any(re.match(r"^" + re.escape(label) + r"(?![a-z0-9])", node)
                    for node in body)
    def separate_named_headings():
        offset = 0
        for name in names:
            target = adapter.fold(name)
            located = next((i for i in range(offset,len(body))
                            if body[i] == target), None)
            if located is None:
                return False
            offset = located+1
        return True
    if not full_bill and not separate_named_headings():
        raise ValueError("Black Lab : plateau officiel non corroboré dans la fiche")
    return names, guest


def verify(candidate, page, catalogue, today):
    if not isinstance(today, dt.date) or not isinstance(candidate, dict):
        raise ValueError("Black Lab : date ou candidat invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("officialDetailFound") is not True
            or triage.words(candidate.get("venue")) != "the black lab"
            or triage.words(candidate.get("city")) != CITY
            or str(candidate.get("department")) != "59"
            or candidate.get("sourcePage") != SOURCE_URL):
        raise ValueError("Black Lab : source privée ou quarantaine incorrecte")
    url = candidate.get("sourceUrl")
    if not isinstance(url,str) or adapter.official_slug(url) is None:
        raise ValueError("Black Lab : fiche HTTPS individuelle obligatoire")
    if not isinstance(page,str) or not 100 <= len(page) <= 500_000:
        raise ValueError("Black Lab : réponse officielle illisible")
    if not isinstance(catalogue,dict) or not all(
            isinstance(catalogue.get(key),list)
            for key in ("artists","venues","events")):
        raise ValueError("Black Lab : catalogue invalide")
    source = {"name":"The Black Lab","city":"Wasquehal",
              "department":"59","url":SOURCE_URL}
    fresh = adapter.detail_candidate(page,url,source,today.isoformat())
    for key in ("sourceUrl","date","source","name","classification",
                "venue","city","department"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("Black Lab : annonce modifiée : "+key)
    if fresh["date"] <= today.isoformat() or not fresh["classification"] or (
            fresh.get("localTime") is not None):
        raise ValueError("Black Lab : concert non futur ou horaire non fiable")
    title = fresh["name"]
    if NONCONCERT.search(triage.words(title)):
        raise ValueError("Black Lab : titre de spectacle ambigu")
    doc = adapter._Parse()
    doc.feed(page)
    if doc.heading_end is None:
        raise ValueError("Black Lab : détail absent")
    nodes = doc.parts[doc.heading_end:]
    names, guest = bill_from_official_body(title, nodes)
    if adapter.CANCEL.search(adapter.fold(" ".join(nodes[:65]))):
        raise ValueError("Black Lab : concert reporté ou annulé")
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE_ID]
    if len(venues) != 1 or triage.words(venues[0].get("city")) != CITY or (
            any(venues[0].get(k) is None for k in ("latitude","longitude"))):
        raise ValueError("Black Lab : Géolocalisation de la salle non confirmée")

    by_name, existing_ids, aliases = {}, set(), set()
    for artist in catalogue["artists"]:
        aid = artist.get("id")
        if not isinstance(aid,str) or not aid:
            raise ValueError("Black Lab : catalogue d'artistes invalide")
        existing_ids.add(aid)
        by_name.setdefault(triage.words(artist.get("name")),[]).append(artist)
        aliases.update(triage.words(a) for a in artist.get("aliases") or []
                       if isinstance(a,str))
    ids, new = [], []
    for name in names:
        key = triage.words(name)
        matches = by_name.get(key,[])
        if len(matches) > 1:
            raise ValueError("Black Lab : identité canonique multiple")
        if matches:
            aid = matches[0]["id"]
        else:
            if key in aliases:
                raise ValueError("Black Lab : alias existant, revue humaine")
            aid = key.replace(" ","-")[:90].strip("-")
            if not 3 <= len(aid) <= 100 or aid in existing_ids:
                raise ValueError("Black Lab : nouvel artiste ambigu")
            new.append({"id":aid,"name":name})
            existing_ids.add(aid)
        ids.append(aid)
    if len(set(ids)) != len(ids):
        raise ValueError("Black Lab : groupe répété")
    if any(e.get("officialUrl") == url or (
            e.get("date") == fresh["date"] and
            e.get("venueId") == VENUE_ID and
            set(e.get("artistIds") or []) & set(ids))
            for e in catalogue["events"]):
        raise ValueError("Black Lab : concert déjà publié")
    eid = "go-c-"+fresh["date"].replace("-","")+"-wasquehal-"+ids[0]
    if len(eid)>150 or any(e.get("id")==eid for e in catalogue["events"]):
        raise ValueError("Black Lab : identifiant déjà réservé")
    return {
        "reviewDecision":"approved",
        "reviewedBy":"automated-official-recheck",
        "reviewedAt":today.isoformat(),
        "officialEvidence":[{
            "url":url,"proofType":"official-organizer-or-venue",
            "checkedAt":today.isoformat(),
            "checkedFields":["artists","date","venue","genre"],
            "officialArtistNames":names,
            "verifiedNewArtists":[a["name"] for a in new],
            "sourceStructure":STRUCTURE,
            **({"unannouncedSupportLabel":guest} if guest else {})
        }],
        "event":{
            "id":eid,"title":" + ".join(names),
            "date":fresh["date"],"time":None,"artistIds":ids,
            "venueId":VENUE_ID,"genres":fresh["classification"],
            "status":"confirmed","officialUrl":url,"sourceType":"salle",
            "organizer":"The Black Lab"
        },
        "newArtists":new
    }
