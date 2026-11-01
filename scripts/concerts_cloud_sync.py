"""Publication cloud des concerts Grosses Ondes, uniquement après approbation documentée.

Source de vérité : docs/grossesondes/concerts.json (GitHub Pages)
Référence immuable : docs/grossesondes/concerts-reference.json
Approbations : dépôt PRIVE GrossesOndes/automation/concerts/approved.json
Aucun candidat brut de la veille n'est publiable.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "docs/grossesondes/concerts.json"
REFERENCE = ROOT / "docs/grossesondes/concerts-reference.json"
APPROVAL_URL = (
    "https://api.github.com/repos/Sarogal/GrossesOndes/contents/"
    "automation/concerts/approved.json?ref=main"
)
SCHEMA = "grossesondes.concert.approvals.v1"


def require(check, message):
    if not check:
        raise ValueError(message)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", value.encode("ascii", "ignore").decode()))


def read_approvals(token):
    require(bool(token), "Jeton privé de lecture absent")
    req = Request(APPROVAL_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "GrossesOndesConcertsCloud/1.0"
    })
    with urlopen(req, timeout=18) as response:
        require(response.status == 200, "Approbations privées indisponibles")
        payload = json.load(response)
    require(payload.get("encoding") == "base64", "Format réponse GitHub inattendu")
    return json.loads(base64.b64decode(payload["content"]).decode("utf-8"))


def validate_catalogue(data):
    require(data.get("schemaVersion") == 1 and
            data.get("mode") == "preview-public-unlisted",
            "Schéma ou visibilité du catalogue non conforme")
    for kind in ("events", "artists", "venues"):
        items = data.get(kind)
        require(isinstance(items, list) and
                len(items) == len({x.get("id") for x in items}) and
                all(isinstance(x.get("id"), str) and x["id"] for x in items),
                "IDs absents ou doublés dans " + kind)
    venue_ids = {x["id"] for x in data["venues"]}
    artist_ids = {x["id"] for x in data["artists"]}
    for event in data["events"]:
        require(
            event.get("venueId") in venue_ids and
            isinstance(event.get("artistIds"), list) and
            bool(event["artistIds"]) and
            all(a in artist_ids for a in event["artistIds"]) and
            isinstance(event.get("date"), str) and
            isinstance(event.get("officialUrl"), str) and
            event["officialUrl"].startswith("https://"),
            "Fiche concert invalide : " + str(event.get("id"))
        )


def protect_reference(reference, current):
    validate_catalogue(reference)
    validate_catalogue(current)
    for kind in ("events", "venues", "artists"):
        initial = reference[kind]
        now = current[kind]
        require(len(now) >= len(initial) and now[:len(initial)] == initial,
                "Référence immuable modifiée ou supprimée : " + kind)
    require(all(current.get(k) == reference.get(k)
                for k in ("schemaVersion", "mode", "dataPolicy")),
            "Métadonnées de sécurité altérées")
    require(len(reference["events"]) == 127 and
            len(reference["venues"]) == 53 and
            len(reference["artists"]) == 193,
            "Référence initiale inattendue")


def norm_date(value):
    require(isinstance(value, str) and
            re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value),
            "Date ISO invalide")
    return dt.date.fromisoformat(value)


def validate_approval(approval, venues, known_artist_ids, today):
    require(approval.get("reviewDecision") == "approved",
            "Événement non approuvé")
    reviewer = approval.get("reviewedBy")
    require(reviewer in ("human", "independent-official-verifier", "automated-official-recheck"),
            "Validateur indépendant absent")
    evidence = approval.get("officialEvidence")
    require(isinstance(evidence, list) and evidence,
            "Aucune preuve officielle indépendante")
    event = approval.get("event")
    require(isinstance(event, dict), "Fiche absente")
    event_id = event.get("id", "")
    require(isinstance(event_id, str) and re.fullmatch(r"go-c-[a-z0-9-]{7,150}", event_id),
            "Identifiant d'événement invalide")
    require(event.get("venueId") in venues,
            "Lieu non connu : nouvel emplacement à vérifier avant publication")
    require(norm_date(event.get("date")) >= today,
            "Concert passé ou non daté")
    require(isinstance(event.get("title"), str) and
            3 <= len(event["title"]) <= 220,
            "Titre invalide")
    official_url = event.get("officialUrl")
    require(isinstance(official_url, str) and
            urlsplit(official_url).scheme == "https" and
            bool(urlsplit(official_url).hostname),
            "Lien officiel HTTPS absent")
    require(any(
        item.get("url") == official_url and
        item.get("proofType") == "official-organizer-or-venue" and
        isinstance(item.get("checkedAt"), str) and item["checkedAt"]
        for item in evidence if isinstance(item, dict)
    ), "Preuve officielle portant sur l'URL exacte absente")
    if reviewer == "automated-official-recheck":
        # An automated recheck is not a human signature: permit only
        # independently fetched, dated first-party Le Rex detail pages.
        require(event.get("venueId") == "le-rex-toulouse" and
                urlsplit(official_url).hostname == "www.lerextoulouse.com" and
                urlsplit(official_url).path.startswith("/fr/programmation/") and
                event.get("sourceType") == "salle",
                "Approbation automatique hors périmètre de salle agréée")
        reviewed_at = norm_date(approval.get("reviewedAt"))
        require(today - dt.timedelta(days=7) <= reviewed_at <= today,
                "Preuve automatique trop ancienne ou future")
        require(any(
            item.get("url") == official_url and
            item.get("proofType") == "official-organizer-or-venue" and
            item.get("checkedAt") == reviewed_at.isoformat() and
            {"artists", "date", "venue", "genre"}.issubset(
                set(item.get("checkedFields") or []))
            for item in evidence if isinstance(item, dict)
        ), "Revérification automatique sans preuves de champs complètes")
    ids = event.get("artistIds")
    require(isinstance(ids, list) and ids and
            len(ids) == len(set(ids)) and
            all(isinstance(x, str) and re.fullmatch(r"[a-z0-9-]+", x)
                for x in ids),
            "Artistes non identifiés")
    new_artists = approval.get("newArtists") or []
    require(isinstance(new_artists, list) and len(new_artists) <= 15,
            "Trop d'artistes nouveaux")
    added = {}
    for artist in new_artists:
        aid = artist.get("id")
        name = artist.get("name")
        require(isinstance(aid, str) and re.fullmatch(r"[a-z0-9-]{3,100}", aid)
                and isinstance(name, str) and 2 <= len(name) <= 120,
                "Artiste nouveau non identifié")
        require(aid not in known_artist_ids and aid not in added,
                "Identifiant d'artiste déjà utilisé")
        added[aid] = {"id": aid, "name": name, "aliases": []}
    require(all(x in known_artist_ids or x in added for x in ids),
            "Artiste non reconnu par le catalogue")
    require(isinstance(event.get("genres"), list) and
            1 <= len(event["genres"]) <= 10 and
            all(isinstance(x, str) and x for x in event["genres"]),
            "Genres non documentés")
    require(event.get("status") == "confirmed", "Concert annulé ou incertain")
    time_value = event.get("time")
    require(time_value is None or
            (isinstance(time_value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_value)),
            "Heure non valide")
    require(event.get("sourceType") in ("organisateur", "salle"),
            "Source tierce seule non admise")
    return event, added


def merge(reference, current, approvals, today):
    protect_reference(reference, current)
    require(approvals.get("schema") == SCHEMA and
            isinstance(approvals.get("approvals"), list),
            "Approbations privées non conformes")
    # Une modification manuelle d'un concert CLOUD ne peut contourner
    # la file privée des approbations et les champs documentés.
    approved_ids = {
        a.get("event", {}).get("id"): a
        for a in approvals["approvals"] if a.get("reviewDecision") == "approved"
    }
    for existing in current["events"][len(reference["events"]):]:
        approval = approved_ids.get(existing["id"])
        require(bool(approval), "Concert cloud publié sans approbation privée")
        expected = approval["event"]
        require(all(existing.get(k) == expected.get(k) for k in
                    ("id", "title", "date", "artistIds", "venueId", "genres",
                     "status", "officialUrl", "sourceType")),
                "Concert cloud modifié hors de son approbation : " + existing["id"])
    result = copy.deepcopy(current)
    ids = {x["id"] for x in result["events"]}
    venues = {x["id"]: x for x in result["venues"]}
    artists = {x["id"]: x for x in result["artists"]}
    counts = {"newEvents": 0, "newArtists": 0, "alreadyPublished": 0, "held": []}
    for entry in approvals["approvals"][:50]:
        try:
            incoming = entry.get("event") or {}
            prior_id = incoming.get("id")
            if prior_id in ids:
                previous = next(e for e in result["events"] if e["id"] == prior_id)
                require(entry.get("reviewDecision") == "approved" and
                        all(previous.get(k) == incoming.get(k) for k in
                            ("id", "title", "date", "artistIds", "venueId", "genres",
                             "status", "officialUrl", "sourceType")),
                        "Approbation existante ne correspond pas à la fiche publiée")
                counts["alreadyPublished"] += 1
                continue
            evt, new_artists = validate_approval(entry, venues, artists, today)
            # Aucune collision non déclarée sur le même lieu, jour et artiste.
            clash = next((other["id"] for other in result["events"]
                          if other["date"] == evt["date"] and
                          other["venueId"] == evt["venueId"] and
                          set(other["artistIds"]).intersection(evt["artistIds"])), None)
            require(not clash, "Doublon potentiel existant : " + str(clash))
            for aid, artist in new_artists.items():
                result["artists"].append(artist)
                artists[aid] = artist
                counts["newArtists"] += 1
            # Champs autorisés explicitement : aucune latitude/longitude inventée.
            item = {k: evt[k] for k in
                    ("id", "title", "date", "artistIds", "venueId", "genres",
                     "status", "officialUrl", "sourceType")}
            item.update({
                "time": evt.get("time"), "timeMeaning": "début du concert" if evt.get("time") else "non confirmé",
                "organizer": evt.get("organizer") or venues[evt["venueId"]]["name"],
                "ticketUrl": evt.get("ticketUrl"),
                "lastVerified": entry.get("reviewedAt") or today.isoformat(),
                "confidence": "Annonce officielle contrôlée; référence vérifiée avant publication",
                "sourceLabel": "Programmation officielle (salle / organisateur)",
                "locationPrecision": "Position connue du catalogue, précision à confirmer",
                "history": [{"date": today.isoformat(),
                             "change": "Ajout après revue des preuves officielles"}]
            })
            result["events"].append(item)
            ids.add(evt["id"])
            counts["newEvents"] += 1
        except (ValueError, KeyError, TypeError) as ex:
            counts["held"].append({"candidateId": entry.get("event", {}).get("id"),
                                   "reason": str(ex)})
    require(len(approvals["approvals"]) <= 50, "Trop d'approbations par lot")
    if counts["newEvents"]:
        result["updatedAt"] = today.isoformat()
        result["edition"] = "v0.6+cloud — vérifications officielles"
    protect_reference(reference, result)
    validate_catalogue(result)
    return result, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "publish"), required=True)
    parser.add_argument("--output", default="/tmp/grossesondes_concerts")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    current = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    token = os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN", "")
    approvals = read_approvals(token) if token else {
        "schema": SCHEMA, "approvals": []
    }
    today = dt.datetime.now(dt.timezone.utc).date()
    candidate, stats = merge(reference, current, approvals, today)
    stats["mode"] = args.mode
    stats["baselineEvents"] = len(reference["events"])
    stats["publicEventsBefore"] = len(current["events"])
    stats["publicEventsAfter"] = len(candidate["events"])
    stats["privateApprovalFeedReadable"] = bool(token)
    (out / "rapport.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "concerts-candidat.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.mode == "publish" and stats["newEvents"]:
        require(bool(token), "Interdiction de publier sans accès aux validations privées")
        CATALOGUE.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Concerts GitHub:", stats["publicEventsBefore"], "→",
          stats["publicEventsAfter"], "publiables en mode", args.mode)


if __name__ == "__main__":
    main()
