#!/usr/bin/env python3
"""Découverte prudente par tournées d'artistes (jamais une approbation).

Exploite les artistes déjà référencés, les sources officielles explicitement
identifiées et le JSON-LD Event/MusicEvent complet. Une page sans date, ville,
salle, pays FR et artiste vérifiables ne produit aucun concert.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import discover
import triage
import livenation_tour_adapter
import seven_weeks_tour_adapter
import inspector_cluzo_tour_adapter
import marillion_tour_adapter
import howlin_jaws_tour_adapter
import tagada_jones_tour_adapter
import tournee_du_coeur_adapter
import stranglers_tour_adapter
import stranglers_linked_tour_adapter
import artist_tour_venue_hints
import cross_artist_tour_review

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "artist-tour-sources.json"
SCHEMA = "grossesondes.concert.discovery.v1"


def artist_ranking(catalogue):
    """Classe tous les artistes par nombre de dates françaises distinctes."""
    dates = defaultdict(set)
    artists = {}
    for item in catalogue.get("artists", []):
        if isinstance(item, dict) and item.get("id") and item.get("name"):
            artists[item["id"]] = item["name"]
    for event in catalogue.get("events", []):
        date = discover.iso_day(event.get("date"))
        if not date:
            continue
        for artist_id in event.get("artistIds", []):
            if artist_id in artists:
                dates[artist_id].add(date)
    return sorted(
        ({"artistId": aid, "artist": name,
          "recordedDateCount": len(dates[aid]),
          "recordedDates": sorted(dates[aid])}
         for aid, name in artists.items()),
        key=lambda row: (-row["recordedDateCount"], row["artist"].casefold(), row["artistId"])
    )


def safe_https(value):
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password


def source_selection(config, ranking, day, max_sources, slot=0):
    rank = {row["artistId"]: row["recordedDateCount"] for row in ranking}
    entries = []
    ids = set()
    if config.get("schema") != "grossesondes.concert.artist_tour_sources.v1":
        raise ValueError("Schéma des sources de tournée inattendu")
    for item in config.get("sources", []):
        if not isinstance(item, dict) or item.get("enabled") is not True:
            continue
        aid = item.get("artistId")
        url = item.get("url")
        if aid not in rank or not safe_https(url):
            raise ValueError("Source artiste inconnue ou URL non HTTPS")
        if item.get("sourceRole") not in ("artist_official", "promoter_official"):
            raise ValueError("Source de tournée non officielle")
        if (aid, url) in ids:
            raise ValueError("Source de tournée dupliquée")
        ids.add((aid, url))
        entries.append(item)
    entries.sort(key=lambda x: (-rank[x["artistId"]], x["artistId"], x["url"]))
    if not entries or max_sources < 1:
        return []
    # Rotation déterministe : groupes de sources répartis sur trois créneaux.
    # On conserve un balayage complet à chaque cycle, sans solliciter 419 sites.
    offset = ((day.toordinal() * 3 + slot) * max_sources) % len(entries)
    return [entries[(offset + i) % len(entries)]
            for i in range(min(max_sources, len(entries)))]


def same_artist(raw, name):
    """Aucune attribution d'une autre affiche à l'artiste surveillé."""
    def values(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [label for x in value for label in values(x)]
        if isinstance(value, dict):
            return values(value.get("name", ""))
        return []
    target = triage.words(name)
    performers = values(raw.get("performer")) + values(raw.get("headliner"))
    if performers:
        return any(triage.words(p) == target for p in performers)
    title = triage.words(discover.safe_name(raw.get("name")))
    # Le titre seul est un indice de line-up, pas une preuve d'approbation.
    # Conserver les frontières de mots : "Unresolvable" != "Resolve".
    return bool(target and re.search(r"(?<!\w)" +
                re.escape(target) + r"(?!\w)", title))


def french_address(raw):
    loc = raw.get("location")
    if isinstance(loc, list):
        loc = next((x for x in loc if isinstance(x, dict)), {})
    if not isinstance(loc, dict):
        return None
    address = loc.get("address")
    if not isinstance(address, dict):
        return None
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    if discover.norm(country) not in ("fr", "france"):
        return None
    venue = discover.safe_name(loc).strip()
    city = str(address.get("addressLocality") or "").strip()
    if not venue or not city:
        return None
    return venue, city


def is_cancellation(raw):
    status = str(raw.get("eventStatus") or "").casefold()
    return any(x in status for x in ("cancel", "postpon", "resched"))


def known_venues(catalogue):
    return {(discover.norm(v.get("name")), livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
            for v in catalogue.get("venues", [])
            if isinstance(v, dict) and v.get("name") and v.get("city")}


def event_candidate(raw, source, artist, catalogue, day):
    start = raw.get("startDate")
    date = discover.iso_day(start) if isinstance(start, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:T|$)", start) else None
    # Année complète et date valide, jamais inférées depuis la tournée.
    if not date or date < day.isoformat():
        return None
    address = french_address(raw)
    if address is None or not same_artist(raw, artist):
        return None
    venue, city = address
    name = discover.safe_name(raw.get("name")).strip() or artist
    if discover.reject_listing(name) and not is_cancellation(raw):
        return None
    cancelled = is_cancellation(raw)
    key = "|".join((source["artistId"], date, discover.norm(city), discover.norm(venue)))
    cid = "artist-tour:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    mapped = known_venues(catalogue).get((discover.norm(venue), livenation_tour_adapter.normalized_city(city)))
    url = raw.get("url")
    # URL de la fiche externe non fiable ? La page officielle reste la preuve
    # d'origine, sans propager le lien externe comme source autorisée.
    if not safe_https(url):
        url = source["url"]
    classification = raw.get("genre") or []
    if isinstance(classification, str):
        classification = [classification]
    if not isinstance(classification, list):
        classification = []
    return {
        "candidateId": cid,
        "source": "artist_official_tour" if source["sourceRole"] == "artist_official"
                  else "promoter_official_tour",
        "sourceUrl": source["url"], "eventDetailUrl": url,
        "sourceRole": source["sourceRole"], "artistId": source["artistId"],
        "date": date, "name": name, "leadArtist": artist,
        "venue": venue, "city": city,
        "venueIdIfKnown": mapped, "newVenueToReview": mapped is None,
        "venueAddressToVerify": True, "coordinatesToVerify": True,
        "classification": classification,
        "genreToConfirm": True, "lineupToConfirm": True,
        "sourceConfidence": "date structurée d'une source officielle; revue indépendante requise",
        "cancellationNotice": cancelled,
        "publicationAllowed": False, "reviewRequired": True,
    }


def scan(catalogue, config, day, max_sources=4, slot=0,
         fetch=discover.download, robots=discover.robots_allow):
    artists = {x["artistId"]: x["artist"] for x in artist_ranking(catalogue)}
    selected = source_selection(config, artist_ranking(catalogue), day, max_sources, slot)
    checks, candidates = [], {}
    robot_cache = {}
    for source in selected:
        report = {"artistId": source["artistId"], "artist": artists[source["artistId"]],
                  "sourceUrl": source["url"], "sourceRole": source["sourceRole"],
                  "structuredEvents": 0, "candidateCount": 0}
        try:
            if not robots(source["url"], robot_cache):
                raise ValueError("robots.txt interdit ou indisponible")
            body, final_url = fetch(source["url"], timeout=15, cap=2_000_000)
            if not discover.same_host(final_url, source["url"]):
                raise ValueError("redirection hors domaine officiel")
            if source.get("adapter") == "howlin_jaws_radical_tour":
                report["htmlShape"] = howlin_jaws_tour_adapter.page_shape(body)
            raw_events = list(discover.read_ld(body))
            report["structuredEvents"] = len(raw_events)

            def retain(proposal):
                if not proposal:
                    return
                old = candidates.get(proposal["candidateId"])
                if old is None:
                    candidates[proposal["candidateId"]] = proposal
                    report["candidateCount"] += 1
                elif proposal["sourceUrl"] != old["sourceUrl"]:
                    old.setdefault("additionalSourceUrls", [])
                    if proposal["sourceUrl"] not in old["additionalSourceUrls"]:
                        old["additionalSourceUrls"].append(proposal["sourceUrl"])

            for raw in raw_events:
                retain(event_candidate(
                    raw, source, artists[source["artistId"]], catalogue, day))

            if source.get("adapter") == "seven_weeks_official_tour":
                tour_rows = seven_weeks_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)
            if source.get("adapter") == "inspector_cluzo_official_tour":
                tour_rows, excluded_festivals = inspector_cluzo_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                report["festivalListingsExcluded"] = excluded_festivals
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "marillion_official_tour":
                tour_rows = marillion_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "howlin_jaws_radical_tour":
                tour_rows = howlin_jaws_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "stranglers_official_ticket_campaign":
                tour_rows = stranglers_linked_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "stranglers_french_2026":
                tour_rows = stranglers_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "tagada_jones_official_tour":
                tour_rows = tagada_jones_tour_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            if source.get("adapter") == "tournee_du_coeur_official_2027":
                tour_rows = tournee_du_coeur_adapter.candidates(
                    body, source, artists[source["artistId"]], catalogue, day)
                report["officialTourEntries"] = len(tour_rows)
                for row in tour_rows:
                    retain(row)

            # Pilote source officielle : chaque fiche /event/ contient sa propre
            # date avec année. Ne jamais hériter de l'année du listing.
            if source.get("detailPathPrefix"):
                links = livenation_tour_adapter.event_links(
                    body, source["url"], source["detailPathPrefix"])
                max_detail = min(max(int(source.get("maxDetailPages", 6)), 1), 12)
                start = ((day.toordinal() * 3 + slot) * max_detail) % len(links) if links else 0
                chosen = [links[(start + i) % len(links)]
                          for i in range(min(max_detail, len(links)))]
                report["detailLinks"] = len(links)
                report["detailPagesRead"] = 0
                report["heldDetailErrors"] = 0
                for detail_url in chosen:
                    try:
                        if not robots(detail_url, robot_cache):
                            raise ValueError("robots.txt détail interdit ou indisponible")
                        detail, final = fetch(detail_url, timeout=12, cap=1_200_000)
                        if not discover.same_host(final, source["url"]):
                            raise ValueError("fiche redirigée hors du domaine officiel")
                        report["detailPagesRead"] += 1
                        structured = list(discover.read_ld(detail))
                        found_structured = False
                        for event in structured:
                            proposal = event_candidate(
                                event, dict(source, url=detail_url),
                                artists[source["artistId"]], catalogue, day)
                            if proposal:
                                found_structured = True
                                retain(proposal)
                        if not found_structured:
                            retain(livenation_tour_adapter.detail_candidate(
                                detail, detail_url, source, artists[source["artistId"]],
                                catalogue, day))
                    except Exception:
                        report["heldDetailErrors"] += 1
            report["status"] = ("parsed_tour" if report.get("officialTourEntries", 0)
                                else "parsed_details" if report.get("detailPagesRead", 0)
                                else "parsed" if raw_events
                                else "source_read_no_structured_event")
        except Exception as exc:
            report["status"] = "held_source_unavailable"
            # Aucun détail d'exception ou d'URL redirigée dans le rapport.
            report["errorType"] = type(exc).__name__
        checks.append(report)
    return list(candidates.values()), checks


def build_report(catalogue, config, day, candidates, checks):
    ranking = artist_ranking(catalogue)
    classified, shortlist, counts = triage.classify(candidates, catalogue)
    return {
        "schema": SCHEMA,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "catalogue": {"url": discover.CATALOG,
                      "edition": catalogue.get("edition"),
                      "events": len(catalogue["events"])},
        "publicationAllowed": False, "automaticPublication": False,
        "sourceChannel": "artist_tour",
        "artistCoverage": {
            "allArtists": len(ranking),
            "artistsWithSeveralDates": sum(x["recordedDateCount"] >= 2 for x in ranking),
            "artistsWithThreeOrMoreDates": sum(x["recordedDateCount"] >= 3 for x in ranking),
            "registeredOfficialSources": sum(bool(x.get("enabled")) for x in config["sources"]),
            "nextArtistSourcesToFind": [
                {"artistId": x["artistId"], "artist": x["artist"],
                 "recordedDateCount": x["recordedDateCount"]}
                for x in ranking if x["recordedDateCount"] >= 2
                and x["artistId"] not in {s["artistId"] for s in config["sources"]}
            ][:30],
        },
        "sourceChecks": checks, "triageCounts": counts,
        "shortlistReviewCount": len(shortlist), "candidates": classified,
        "notes": [
            "Source officielle de tournée != approbation indépendante.",
            "Une page ne livrant pas de dates structurées est signalée, jamais devinée.",
            "Nouveaux lieux sans adresse GPS et concerts sans genre vérifié restent en revue.",
            "Aucune publication de catalogues et aucune suppression d'événements.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--sources", default=str(SOURCES))
    parser.add_argument("--max-sources", type=int, default=4)
    parser.add_argument("--slot", type=int, default=None)
    args = parser.parse_args(argv)
    if args.max_sources < 1 or args.max_sources > 20:
        parser.error("--max-sources doit être compris entre 1 et 20")
    dest = Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    day = discover.today_fr()
    slot = (dt.datetime.now(discover.ZoneInfo("Europe/Paris")).hour // 6
            if args.slot is None else args.slot)
    if not 0 <= slot <= 3:
        parser.error("--slot doit être compris entre 0 et 3")
    # Fail closed : le catalogue réellement publié doit être accessible.
    try:
        catalogue = discover.json_url(discover.CATALOG)
        if (catalogue.get("schemaVersion") != 1
                or not isinstance(catalogue.get("events"), list)
                or not isinstance(catalogue.get("artists"), list)
                or not isinstance(catalogue.get("venues"), list)):
            raise ValueError("Schéma du catalogue public non conforme")
        config = json.loads(Path(args.sources).read_text(encoding="utf-8"))
        candidates, checks = scan(catalogue, config, day, args.max_sources, slot)
        # Réconciliation documentaire sans changement d'identité des pistes.
        candidates, reconciled = artist_tour_venue_hints.annotate(
            candidates, catalogue, artist_tour_venue_hints.load())
        candidates, shared_groups = cross_artist_tour_review.annotate(candidates)
        report = build_report(catalogue, config, day, candidates, checks)
        report["sharedBillReviewGroups"] = shared_groups
        report["venueReconciliations"] = {
            "count": len(reconciled), "candidateIds": reconciled,
            "publicationAllowed": False,
        }
    except Exception as exc:
        print("ÉCHEC FERMÉ : source/catalogue/registre invalide : " +
              type(exc).__name__, file=sys.stderr)
        return 2
    (dest / "candidates.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Découverte Concerts — tournées officielles — " + day.isoformat(),
        "", "Artistes suivis : " + str(report["artistCoverage"]["allArtists"]),
        "Artistes avec au moins deux dates : " + str(report["artistCoverage"]["artistsWithSeveralDates"]),
        "Sources interrogées : " + str(len(checks)),
        "Pistes en revue privée : " + str(len(report["candidates"])),
        "Nouvelles salles à vérifier : " + str(sum(x["newVenueToReview"] for x in report["candidates"])),
        "Publication : **interdite**.", "",
        "## Sources contrôlées",
        *("- " + x["artist"] + " : " + x["status"] +
          " — " + str(x["candidateCount"]) + " piste(s)" for x in checks),
    ]
    (dest / "rapport.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Les rapports GitHub Actions peuvent être indisponibles ou difficiles
    # à consulter. Laisser un diagnostic borné par source directement dans
    # les logs, sans liens externes redirigés ni détails d'exceptions.
    for item in checks:
        print("TOUR_SOURCE_CHECK:",
              "artist=" + str(item["artistId"]),
              "status=" + str(item.get("status", "unknown")),
              "structured=" + str(item.get("structuredEvents", 0)),
              "tour_entries=" + str(item.get("officialTourEntries", 0)),
              "festivals_excluded=" + str(item.get("festivalListingsExcluded", 0)),
              "detail_links=" + str(item.get("detailLinks", 0)),
              "detail_read=" + str(item.get("detailPagesRead", 0)),
              "detail_errors=" + str(item.get("heldDetailErrors", 0)),
              "candidates=" + str(item.get("candidateCount", 0)),
              "error_type=" + str(item.get("errorType", "none")),
              "html_tokens=" + str(item.get("htmlShape", {}).get("visibleTokens", 0)),
              "html_chars=" + str(item.get("htmlShape", {}).get("htmlChars", 0)),
              "artist_title=" + str(item.get("htmlShape", {}).get("artistTitleFound", False)),
              "upcoming_heading=" + str(item.get("htmlShape", {}).get("upcomingHeadingFound", False)),
              "date_tokens=" + str(item.get("htmlShape", {}).get("completeDateTokens", 0)))
    print("CROSS_ARTIST_REVIEW_CHECK:",
          "potential_shared_bill_groups=" + str(report["sharedBillReviewGroups"]),
          "lineup_confirmed=0", "publication=forbidden")
    print("VENUE_RECONCILIATION_CHECK:",
          "documented_matches=" + str(report["venueReconciliations"]["count"]),
          "publication=forbidden")
    print("Tournées : ", len(checks), "sources /",
          len(report["candidates"]), "candidats ; aucune publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
