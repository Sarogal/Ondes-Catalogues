"""Préparer, SANS PUBLIER, des propositions issues du backlog privé.

Chaque candidat est corroboré par:
- une fiche source OpenAgenda indexée, avec séance exacte, statut programmé,
  commune, titre, salle, âge et coordonnées non contradictoires ;
- une géolocalisation de salle inscrite dans le registre indépendant ;
- le contrôle HTML officiel existant (proof_text.verify_event).
Le synchroniseur public garde le dernier mot via merge_policy.merge.
"""
from datetime import date
from hashlib import sha256
import json
import re
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from proof import meters, norm
from proof_text import verify_event
from venue_registry import VENUES

ODS = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
       "evenements-publics-openagenda/records")
FIELDS = ("uid,title_fr,description_fr,canonicalurl,originagenda_title,"
          "location_city,location_name,location_countrycode,location_department,"
          "location_region,location_coordinates,timings,status,age_min,age_max")
STRONG_FAMILY = ("jeune public", "pour enfants", "pour les enfants", "tout petits",
                 "tout petits", "tout petits", "bebes", "bebe", "pour les familles",
                 "des 3 ans", "des 4 ans", "des 5 ans", "des 6 ans",
                 "eveil musical", "comptines", "spectacle familial")
MUSIC = ("concert", "musical", "musique", "sonore", "comptines", "cine concert")


def official_family(title, description):
    """A musical genre alone (e.g. cinéma-concert) does not imply child suitability."""
    content = norm(str(title) + " " + str(description))
    return (any(s in content for s in STRONG_FAMILY) and
            any(m in content for m in MUSIC))


def venue_for(city, venue):
    for place in VENUES:
        if norm(city) == norm(place["city"]) and any(
                norm(venue) == norm(alias) for alias in place["aliases"]):
            return place
    return None


def get_ods(uid):
    if not re.fullmatch(r"[0-9]{1,12}", str(uid)):
        raise ValueError("UID OpenAgenda invalide")
    args = urlencode({"limit": 2, "select": FIELDS, "where": "uid='" + str(uid) + "'"})
    req = Request(ODS + "?" + args, headers={
        "Accept": "application/json",
        "User-Agent": "OndesCatalogues-Outings-Review/1.0"})
    with urlopen(req, timeout=20) as response:
        if urlparse(response.geturl()).hostname != "public.opendatasoft.com":
            raise ValueError("Redirection source inattendue")
        data = response.read(150_001)
    if len(data) > 150_000:
        raise ValueError("Fiche index trop volumineuse")
    payload = json.loads(data)
    rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) != 1 or str(rows[0].get("uid")) != str(uid):
        raise ValueError("UID absent, multiple ou changé")
    return rows[0]


def timings_on_day(value, day):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    sessions = set()
    for timing in value:
        if not isinstance(timing, dict):
            continue
        begin = timing.get("begin")
        if not isinstance(begin, str) or begin[:10] != day:
            continue
        match = re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):([0-5]\d):[0-5]\d(?:[+-]\d{2}:\d{2}|Z)",
            begin)
        if match:
            sessions.add(match.group(1) + ":" + match.group(2))
    return sorted(sessions)


def category_for(title):
    t = norm(title)
    if "cine concert" in t:
        return "cine-concert", "Ciné-concert"
    if "conte musical" in t:
        return "conte-musical", "Conte musical"
    if "eveil musical" in t:
        return "eveil-musical", "Éveil musical"
    if "atelier musical" in t:
        return "atelier-musical", "Atelier musical"
    if "spectacle musical" in t:
        return "spectacle-musical", "Spectacle musical"
    if "concert" in t:
        return "concert", "Concert"
    return None


def safe_slug(value):
    s = norm(value).replace(" ", "-").strip("-")
    return re.sub(r"-+", "-", s)[:45].strip("-")


def build_event(lead, row, today):
    """Return (event, reason); no guessed value, no broad date periods."""
    if not isinstance(lead, dict) or not isinstance(row, dict):
        return None, "données malformées"
    uid = str(lead.get("external_id", ""))
    if not re.fullmatch(r"\d{1,12}", uid) or str(row.get("uid")) != uid:
        return None, "identifiant source différent"
    url = str(row.get("canonicalurl", ""))
    if (urlparse(url).hostname != "openagenda.com" or
            url != lead.get("source_url")):
        return None, "URL OpenAgenda officielle différente"
    title, city, venue = (str(row.get(k, "")) for k in
                           ("title_fr", "location_city", "location_name"))
    if (norm(title) != norm(lead.get("title")) or
            norm(city) != norm(lead.get("city")) or
            norm(venue) != norm(lead.get("venue"))):
        return None, "titre, ville ou salle différente de la découverte"
    if str(row.get("location_countrycode", "")).upper() != "FR":
        return None, "territoire hors périmètre vérifiable par ce collecteur"
    if not official_family(title, row.get("description_fr", "")):
        return None, "cible jeune public non explicitement confirmée"
    cat = category_for(title)
    if not cat:
        return None, "catégorie musicale incertaine"
    try:
        day = date.fromisoformat(lead["date_start"])
    except (ValueError, KeyError, TypeError):
        return None, "date incorrecte"
    if lead.get("date_end") != day.isoformat() or not today <= day:
        return None, "date expirée ou période ambiguë"
    times = timings_on_day(row.get("timings"), day.isoformat())
    if not times:
        return None, "horaires et séance exacte non présents"
    try:
        status = row["status"]
        if isinstance(status, str):
            status = json.loads(status)
        if not isinstance(status, dict) or status.get("id") != 1:
            return None, "événement annulé, reporté ou statut incertain"
    except (KeyError, ValueError, TypeError):
        return None, "statut non documenté"
    place = venue_for(city, venue)
    if place is None:
        return None, "salle absente du registre de GPS indépendant"
    coords = row.get("location_coordinates")
    if not isinstance(coords, dict):
        return None, "GPS source absent ou non structuré"
    try:
        point = float(coords["lat"]), float(coords["lon"])
        if meters(point, (place["lat"], place["lng"])) > 100:
            return None, "coordonnées de la source contradictoires avec le registre"
    except (KeyError, ValueError, TypeError, OverflowError):
        return None, "coordonnées de source invalides"
    department = row.get("location_department")
    region = row.get("location_region")
    if not isinstance(department, str) or not department.strip():
        return None, "département manquant"
    if not isinstance(region, str) or not region.strip():
        return None, "région manquante"
    source_label = row.get("originagenda_title")
    if not isinstance(source_label, str) or not source_label.strip():
        return None, "organisateur non identifié"
    identifier = (safe_slug(city) + "-" + safe_slug(title) + "-" +
                  uid + "-" + day.isoformat())
    event = {
        "id": identifier, "title": title, "category": cat[0],
        "category_label": cat[1], "date_start": day.isoformat(),
        "date_end": day.isoformat(), "time": " et ".join(times),
        "city": city, "department": department,
        "region": region, "venue": venue, "source_url": url,
        "source_label": source_label, "verified_at": today.isoformat(),
        "geo_verified_at": today.isoformat(), "geo_precision": "venue",
        "lat": place["lat"], "lng": place["lng"]
    }
    # Preserve structured age only if actually available; do not infer it.
    for field in ("age_min", "age_max"):
        raw = row.get(field)
        if raw is not None:
            if type(raw) not in (int, float) or not 0 <= raw <= 18:
                return None, "âge source invalide"
            event[field] = raw
    return event, "candidat structuré complet"


def preview(leads, public, today, fetch=get_ods, verify=verify_event, limit=100):
    """No mutation, and no public candidate without independent HTML verification."""
    if not isinstance(leads, list) or not isinstance(public, dict):
        raise ValueError("Backlog / catalogue malformé")
    published_ids = {e["id"] for e in public["events"]}
    published_signatures = {
        (norm(e.get("title")), norm(e.get("city")),
         norm(e.get("venue")), e.get("date_start"))
        for e in public["events"]
    }
    seen = set()
    accepted = []
    reasons = {}
    examined = queries = 0
    cache = {}
    for lead in leads:
        if not isinstance(lead, dict) or lead.get("collector") not in (
                "opendatasoft-index", "openagenda-v2"):
            continue
        if not venue_for(lead.get("city", ""), lead.get("venue", "")):
            reasons["lieu non encore documenté"] = reasons.get(
                "lieu non encore documenté", 0) + 1
            continue
        key = (lead.get("external_id"), lead.get("date_start"),
               norm(lead.get("venue")))
        if key in seen:
            continue
        seen.add(key)
        if examined >= limit:
            break
        examined += 1
        uid = str(lead.get("external_id", ""))
        if not re.fullmatch(r"\d{1,12}", uid):
            reasons["UID manquant"] = reasons.get("UID manquant", 0) + 1
            continue
        if uid not in cache:
            try:
                cache[uid] = fetch(uid)
                queries += 1
            except Exception:
                cache[uid] = None
        if cache[uid] is None:
            reasons["source index inaccessible"] = reasons.get(
                "source index inaccessible", 0) + 1
            continue
        try:
            event, reason = build_event(lead, cache[uid], today)
        except (ValueError, TypeError, KeyError, OverflowError):
            event, reason = None, "métadonnées source incorrectes"
        if event is not None:
            signature = (norm(event["title"]), norm(event["city"]),
                         norm(event["venue"]), event["date_start"])
            if event["id"] in published_ids or signature in published_signatures:
                event, reason = None, "déjà publié"
            else:
                ok, reason = verify(event, public["events"])
                if not ok:
                    event = None
                else:
                    published_ids.add(event["id"])
                    published_signatures.add(signature)
                    accepted.append(event)
        if event is None:
            reasons[reason] = reasons.get(reason, 0) + 1
    return {"examined": examined, "network_requests": queries,
            "accepted": accepted, "rejected_by_reason": reasons,
            "public_changes": 0, "mode": "PREVIEW_ONLY"}
