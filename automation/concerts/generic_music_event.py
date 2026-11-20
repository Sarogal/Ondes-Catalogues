"""Source-wide first-party structured concert verifier for explicitly reviewed venues.

Discovery feeds, registry rows and sources.json never grant an additional
publishing host: this small immutable map is reviewed independently from them.
There are NO per-concert names, IDs, dates or acceptance URLs in this module.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

import discover
import official_rss_jsonld_bridge as bridge
import triage
from official_recheck import norm, slug

# Only the independently reviewed, COMMITTED manifest is allowed to grant
# a first-party venue scope. Sources, candidates and private registry entries
# never update this map. Adding a venue requires review and contract CI.
MANIFEST = Path(__file__).with_name("generic_first_party_venue_specs_v1.json")


def load_specs(path=MANIFEST):
    """Read a strict manifest; malformed authority fails CLOSED at startup."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(data, dict)
            or set(data) != {"schema", "venues"}
            or data["schema"] != "grossesondes.concert.reviewed-venue-specs.v1"
            or not isinstance(data["venues"], dict)
            or not data["venues"]):
        raise ValueError("Manifeste de salles agréées invalide")
    specs, seen = {}, set()
    for venue_id, row in data["venues"].items():
        if (not isinstance(venue_id, str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", venue_id)
                or not isinstance(row, dict)
                or set(row) != {"name", "city", "department", "host", "base",
                                "eventPathPrefix"}):
            raise ValueError("Identité de salle agréée non conforme")
        name, city, department, host, base = (
            row["name"], row["city"], row["department"],
            row["host"], row["base"])
        event_prefix = row["eventPathPrefix"]
        if (not isinstance(name, str) or not 2 <= len(name) <= 100
                or name != name.strip()
                or not isinstance(city, str) or not 2 <= len(city) <= 100
                or city != city.strip()
                or not isinstance(department, str)
                or not re.fullmatch(r"(?:[0-9]{2,3}|2A|2B)", department)
                or not isinstance(host, str)
                or not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,24}", host)
                or not isinstance(base, str)
                or base != "https://" + host + "/"
                or not isinstance(event_prefix, str)
                or not re.fullmatch(r"/(?:[a-z0-9-]{2,40}/){1,3}", event_prefix)):
            raise ValueError("Domaine HTTPS / géographie agréés non conformes")
        identity = (norm(name), norm(city), department)
        if identity in seen:
            raise ValueError("Salle ou hôte officiel agréé en doublon")
        seen.add(identity)
        specs[venue_id] = MappingProxyType(dict(row))
    return MappingProxyType(specs)


SPECS = load_specs()
ALLOWED_HOSTS = frozenset(row["host"] for row in SPECS.values())


def trusted_spec(candidate):
    """Select a committed venue identity, not a venue claimed by a feed."""
    if not isinstance(candidate, dict):
        return None
    for venue_id, spec in SPECS.items():
        if (norm(candidate.get("venue")) != norm(spec["name"])
                or norm(candidate.get("city")) != norm(spec["city"])
                or str(candidate.get("department")) != spec["department"]):
            continue
        url = candidate.get("sourceUrl")
        if bridge.official_event_url(url, spec["base"]):
            parts = urlsplit(url)
            path = parts.path
            prefix = spec["eventPathPrefix"]
            if (parts.hostname == spec["host"]
                    and path.startswith(prefix)
                    and re.fullmatch(r"[a-z0-9-]{5,160}/?",
                                     path[len(prefix):])):
                return venue_id, spec
    return None


def verify(candidate, html_text, catalogue, today):
    """Re-fetching is performed by official_recheck, before this verifier."""
    if (not isinstance(today, dt.date)
            or not isinstance(candidate, dict)
            or candidate.get("source") != "agenda_officiel_structuré"
            or candidate.get("reviewBucket") not in {
                "genre_tag_review", "genre_unknown"}
            or candidate.get("possibleExistingConcert") is True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True):
        raise ValueError("Piste structurée non agréée")
    # Only the fresh event-level structured genre may requalify an
    # unconfirmed discovery. A registry bucket is never proof on its own.
    newly_qualified = candidate["reviewBucket"] == "genre_unknown"
    if newly_qualified and triage.genre_evidence({
            "classification": candidate.get("classification")}):
        raise ValueError("Genre déjà établi : catégorie de revue incohérente")
    match = trusted_spec(candidate)
    if match is None:
        raise ValueError("Salle/domaine non agréés pour la voie structurée")
    venue_id, source = match
    url = candidate["sourceUrl"]
    # The sourcePage is advisory only but must be on the same first-party host;
    # it cannot launder third-party discovery into a trusted event.
    page = candidate.get("sourcePage")
    if page is not None and not discover.same_host(page, source["base"]):
        raise ValueError("Page de découverte hors domaine de la salle")
    if not isinstance(catalogue, dict):
        raise ValueError("Catalogue absent")
    venues = [v for v in catalogue.get("venues", [])
              if v.get("id") == venue_id]
    if (len(venues) != 1
            or norm(venues[0].get("name")) != norm(source["name"])
            or norm(venues[0].get("city")) != norm(source["city"])
            or str(venues[0].get("department")) != source["department"]):
        raise ValueError("Salle publique non réconciliée avec sa source")
    if not isinstance(html_text, str) or len(html_text) > 1_000_000:
        raise ValueError("Preuve structurée illisible")

    first_party = {
        "url": source["base"], "name": source["name"],
        "city": source["city"], "department": source["department"],
    }
    fresh = bridge.candidate_from_event_page(
        candidate, html_text, url, first_party, set(), today,
        read_ld=discover.read_ld, venue_candidate=discover.venue_candidate,
        norm=discover.norm, allow_generic_event=True)
    if fresh is None:
        raise ValueError("Détail de concert officiel non corroboré")
    # Genre is the ONLY permitted change. Date, names, site, city,
    # department, URL and optional unnamed guest must still match exactly.
    for field in ("date", "name", "leadArtist", "venue", "city",
                  "department", "classification", "sourceUrl",
                  "unannouncedSupportLabel"):
        if newly_qualified and field == "classification":
            continue
        if fresh.get(field) != candidate.get(field):
            raise ValueError("Identité du concert changée lors de la revue: " + field)

    # Require exactly ONE event node. A mixed MusicEvent + unrelated Event in
    # the same page must never lend the former its genre or artist names.
    events = [v for v in discover.read_ld(html_text)
              if isinstance(v, dict) and (
                  bridge._event_types(v.get("@type")) & {"MusicEvent", "Event"})]
    if len(events) != 1:
        raise ValueError("Plusieurs événements structurés ou aucun")
    event = events[0]
    raw_genres = event.get("genre")
    if isinstance(raw_genres, str):
        raw_genres = [raw_genres]
    if (not isinstance(raw_genres, list)
            or not 1 <= len(raw_genres) <= 20
            or not all(isinstance(g, str) and 2 <= len(g.strip()) <= 80
                       for g in raw_genres)
            or not triage.genre_evidence({"classification": raw_genres})):
        raise ValueError("Genre musical officiel précis absent")
    genres = [g.strip() for g in raw_genres]
    if genres != fresh.get("classification"):
        raise ValueError("Genre officiel différent de la découverte")
    bill = bridge.official_named_bill(event.get("performer"))
    if bill is None:
        raise ValueError("Interprètes nominatifs non corroborés")
    names, unnamed = bill
    if fresh.get("leadArtist") != " + ".join(names):
        raise ValueError("Programmation structurée non réconciliée")
    if unnamed != fresh.get("unannouncedSupportLabel"):
        raise ValueError("Guest non nommé ambigu")

    return approve_verified_bill(
        catalogue, venue_id, source, url, today, fresh["date"],
        names, genres, unnamed, "verified-first-party-structured-event-v1")


def approve_verified_bill(catalogue, venue_id, source, url, today,
                          when, names, genres, unnamed, structure):
    """Common, strict artist/duplicate/approval builder for official proofs.

    Called only after an independent fresh first-party STRUCTURED or VISIBLE
    exact-lineup verifier. Discovery data NEVER reaches this function alone.
    The publisher separately enforces both proof schemas.
    """
    if (not isinstance(catalogue, dict) or not isinstance(today, dt.date)
            or venue_id not in SPECS or source != SPECS[venue_id]
            or not isinstance(when, str)
            or not isinstance(names, list) or not names
            or any(not isinstance(n, str) or not 2 <= len(n.strip()) <= 120
                   for n in names)
            or len({norm(n) for n in names}) != len(names)
            or not isinstance(genres, list) or not genres
            or any(not isinstance(g, str) or not 2 <= len(g.strip()) <= 80
                   for g in genres)
            or not triage.genre_evidence({"classification": genres})
            or structure not in {
                "verified-first-party-structured-event-v1",
                "verified-first-party-visible-bill-v1",
            }):
        raise ValueError("Preuve officielle ou programmation générique invalide")
    try:
        event_date = dt.date.fromisoformat(when)
    except (TypeError, ValueError):
        raise ValueError("Date officielle invalide")
    if event_date < today:
        raise ValueError("Concert officiel passé")
    known_names, aliases = {}, set()
    for a in catalogue.get("artists", []):
        if not isinstance(a, dict):
            raise ValueError("Catalogue artiste invalide")
        known_names.setdefault(norm(a.get("name")), []).append(a)
        aliases.update(norm(x) for x in a.get("aliases", [])
                       if isinstance(x, str) and norm(x))
    existing_ids = {a.get("id") for a in catalogue.get("artists", [])}
    ids, new_artists = [], []
    for name in names:
        matching = known_names.get(norm(name), [])
        if len(matching) > 1 or (not matching and norm(name) in aliases):
            raise ValueError("Artiste ou alias ambigu")
        ident = matching[0]["id"] if matching else slug(name)
        if (not isinstance(ident, str) or len(ident) < 3
                or (not matching and ident in existing_ids)):
            raise ValueError("Identifiant artiste ambigu")
        ids.append(ident)
        if not matching:
            new_artists.append({"id": ident, "name": name})
    if len(set(ids)) != len(ids):
        raise ValueError("Interprètes doublonnés")
    for e in catalogue.get("events", []):
        if not isinstance(e, dict):
            raise ValueError("Catalogue événement invalide")
        if e.get("officialUrl") == url:
            raise ValueError("URL officielle déjà publiée")
        if (e.get("date") == when and e.get("venueId") == venue_id
                and set(e.get("artistIds") or []).intersection(ids)):
            raise ValueError("Concert déjà publié au même endroit ce jour")
    concert_id = ("go-c-" + when.replace("-", "") + "-"
                  + slug(source["city"]) + "-" + slug(names[0]))
    if any(e.get("id") == concert_id for e in catalogue.get("events", [])):
        raise ValueError("Collision identifiant de concert")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "sourceStructure": structure,
            "officialArtistNames": names,
            "verifiedVenueId": venue_id,
            **({"officialGenreLabels": genres,
                "visibleBillProfile": "heading-artist-genre-v1"}
               if structure == "verified-first-party-visible-bill-v1" else {}),
            **({"unannouncedSupportLabel": unnamed} if unnamed else {}),
        }],
        "event": {
            "id": concert_id, "title": " + ".join(names), "date": when,
            "time": None, "artistIds": ids, "venueId": venue_id,
            "genres": genres, "status": "confirmed", "officialUrl": url,
            "sourceType": "salle", "organizer": source["name"],
        },
        "newArtists": new_artists,
    }
