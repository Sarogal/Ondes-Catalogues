"""Strict independent first-party qualification of Cave aux Poètes concert bills.

The discovery card merely nominates a candidate. On a second fetch, the
individual venue article must independently repeat every named artist,
the full date, venue and explicit genre.  Unlike opening-door times, a
clock labelled "CONCERTS :" proves a musical start; absent clocks stay null.
This verifier never changes the public catalogue or private approvals.
"""
from __future__ import annotations

import datetime as dt
import re

import cave_poetes_adapter as source

SOURCE = "agenda_officiel_cave_poetes_detail"
VENUE = "la-cave-aux-poetes-roubaix"
STRUCTURE = "cave-poetes-first-party-named-artist-blocks"
GENRES = frozenset({
    "post punk", "punk", "hardcore", "metalcore", "deathcore",
    "hard rock", "metal", "stoner", "sludge", "grindcore", "thrash", "doom",
})
UNANNOUNCED = frozenset({
    "guest", "special guest", "premiere partie", "1ere partie",
    "1re partie", "support", "surprise", "a confirmer", "tba",
    "invite surprise", "artiste surprise",
})
UNSAFE_NAMES = frozenset({
    "guest", "special guest", "premiere partie", "support", "surprise",
    "tba", "a confirmer", "festival", "tribute", "hommage",
})


def verify(candidate, page, catalogue, today):
    if not isinstance(candidate, dict) or not isinstance(today, dt.date):
        raise ValueError("Cave : entrée non valide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("officialDetailFound") is not True
            or candidate.get("venueCatalogueId") != VENUE
            or source.norm(candidate.get("venue")) != "la cave aux poetes"
            or source.norm(candidate.get("city")) != "roubaix"
            or str(candidate.get("department")) != "59"
            or candidate.get("sourcePage") != "https://caveauxpoetes.com/agenda/"):
        raise ValueError("Cave : source et quarantaine non vérifiées")
    url = candidate.get("sourceUrl")
    if not isinstance(url, str) or source.url_ok(url) != url:
        raise ValueError("Cave : URL de fiche officielle invalide")
    if not isinstance(page, str) or not 100 <= len(page) <= 500_000:
        raise ValueError("Cave : détail absent ou illisible")
    if not isinstance(catalogue, dict) or any(
            not isinstance(catalogue.get(x), list)
            for x in ("artists", "venues", "events")):
        raise ValueError("Cave : catalogue illisible")

    doc = source.Page(detail=True)
    doc.feed(page)
    if len(doc.rows) != 1:
        raise ValueError("Cave : un unique article de concert nécessaire")
    raw_names = doc.rows[0]["artists"]
    guest = None
    if len(raw_names) > 1 and source.norm(raw_names[-1]) in UNANNOUNCED:
        guest = source.norm(raw_names[-1])
    names = raw_names[:-1] if guest else raw_names
    keys = [source.norm(name) for name in names]
    if (not keys or len(set(keys)) != len(keys)
            or any(not 3 <= len(name) <= 100 or name in UNSAFE_NAMES
                   for name in keys)):
        raise ValueError("Cave : groupe non nommé ou affiche ambiguë")
    # This card is only a second-read parameter, NEVER an independent proof.
    # The venue parser itself still requires each exact artist inside the
    # event article; it ignores related items outside this article.
    card = {
        "date": candidate.get("date"),
        "artists": [x.strip() for x in candidate.get("name", "").split(" + ")],
        "venue": "La Cave aux Poètes",
        "status": "",
    }
    source_record = {
        "name": "La Cave aux Poètes", "city": "Roubaix",
        "department": "59", "url": "https://caveauxpoetes.com/agenda/",
    }
    fresh = source.candidate(page, url, card, source_record, today.isoformat())
    for key in ("source", "sourceUrl", "sourcePage", "name", "leadArtist",
                "date", "venue", "venueCatalogueId", "city", "department",
                "classification", "localTime", "officialDetailFound"):
        if candidate.get(key) != fresh.get(key):
            raise ValueError("Cave : annonce modifiée depuis la découverte : " + key)
    if dt.date.fromisoformat(fresh["date"]) <= today:
        raise ValueError("Cave : concert passé")
    if len(fresh["classification"]) != 1 or source.norm(
            fresh["classification"][0]) not in GENRES:
        raise ValueError("Cave : genre pertinent non démontré")
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE]
    if (len(venues) != 1 or source.norm(venues[0].get("city")) != "roubaix"
            or any(venues[0].get(k) is None
                   for k in ("latitude", "longitude"))):
        raise ValueError("Cave : salle géolocalisée non certifiée")

    known_names, aliases, reserved = {}, set(), set()
    for artist in catalogue["artists"]:
        aid = artist.get("id")
        if not isinstance(aid, str) or not aid:
            raise ValueError("Cave : identité publique incohérente")
        reserved.add(aid)
        known_names.setdefault(source.norm(artist.get("name")), []).append(artist)
        aliases.update(source.norm(a) for a in artist.get("aliases") or []
                       if isinstance(a, str))
    ids, added = [], []
    for name in names:
        key = source.norm(name)
        matched = known_names.get(key, [])
        if len(matched) > 1:
            raise ValueError("Cave : plusieurs artistes canoniques")
        if matched:
            aid = matched[0]["id"]
        else:
            if key in aliases:
                raise ValueError("Cave : alias déjà connu à confirmer")
            aid = key.replace(" ", "-")[:90].strip("-")
            if not 3 <= len(aid) <= 100 or aid in reserved:
                raise ValueError("Cave : nouvel artiste sans identité stable")
            added.append({"id": aid, "name": name})
            reserved.add(aid)
        ids.append(aid)
    if len(ids) != len(set(ids)):
        raise ValueError("Cave : groupe en double")
    if any(e.get("officialUrl") == url or (
            e.get("date") == fresh["date"] and e.get("venueId") == VENUE
            and set(e.get("artistIds") or []) & set(ids))
            for e in catalogue["events"]):
        raise ValueError("Cave : concert déjà présent")
    event_id = "go-c-" + fresh["date"].replace("-", "") + "-roubaix-" + ids[0]
    if len(event_id) > 150 or any(e.get("id") == event_id
                                  for e in catalogue["events"]):
        raise ValueError("Cave : identifiant de concert déjà utilisé")

    proof = {
        "url": url,
        "proofType": "official-organizer-or-venue",
        "checkedAt": today.isoformat(),
        "checkedFields": ["artists", "date", "venue", "genre"] +
                         (["concertStartTime"] if fresh["localTime"] else []),
        "sourceStructure": STRUCTURE,
        "officialArtistNames": names,
        "verifiedNewArtists": [a["name"] for a in added],
        "officialVenue": "La Cave aux Poètes",
        **({"unannouncedSupportLabel": guest} if guest else {}),
    }
    if fresh["localTime"]:
        proof["concertStartTimeConfirmed"] = fresh["localTime"]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [proof],
        "event": {
            "id": event_id, "title": " + ".join(names), "date": fresh["date"],
            "time": fresh["localTime"], "artistIds": ids, "venueId": VENUE,
            "genres": fresh["classification"], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "La Cave aux Poètes",
        },
        "newArtists": added,
    }
