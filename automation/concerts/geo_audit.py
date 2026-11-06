#!/usr/bin/env python3
"""Lecture seule : prioriser les repères approximatifs de la carte Concerts."""
import argparse
import collections
import datetime as dt
import json
import math
import urllib.request
from pathlib import Path

CATALOGUE_URL = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/concerts.json"
MAX_BYTES = 2_000_000
COARSE_MARKERS = (
    "centre de commune", "centre indicatif", "position indicative", "à recontrôler",
    "a recontroler", "coordonnées indicatives", "coordonnees indicatives",
    "à préciser", "a preciser", "approximation communale",
)


def load_live_catalogue(url=CATALOGUE_URL):
    """Aucun téléchargement tiers : source GitHub Pages autorisée et fixe."""
    if url != CATALOGUE_URL:
        raise ValueError("Source Concerts non autorisée")
    request = urllib.request.Request(url, headers={"User-Agent": "GrossesOndes-GeoAudit/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Catalogue trop volumineux")
    return json.loads(data.decode("utf-8"))


def validate_catalogue(data):
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("Schéma Concerts inconnu")
    venues, events = data.get("venues"), data.get("events")
    if not isinstance(venues, list) or not isinstance(events, list):
        raise ValueError("Listes de salles et de concerts manquantes")
    venue_ids = [v.get("id") for v in venues if isinstance(v, dict)]
    event_ids = [e.get("id") for e in events if isinstance(e, dict)]
    if (len(venue_ids) != len(venues) or len(event_ids) != len(events)
            or len(set(venue_ids)) != len(venues)
            or len(set(event_ids)) != len(events)
            or not all(isinstance(x, str) and x for x in venue_ids + event_ids)):
        raise ValueError("Identifiants de salle ou de concert invalides ou dupliqués")
    if any(e.get("venueId") not in set(venue_ids) for e in events):
        raise ValueError("Un concert pointe vers une salle inconnue")
    return venues, events


def geo_status(venue):
    lat, lon = venue.get("latitude"), venue.get("longitude")
    if (not isinstance(lat, (float, int)) or isinstance(lat, bool)
            or not isinstance(lon, (float, int)) or isinstance(lon, bool)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return "missing_coordinates"
    precision = str(venue.get("geoPrecision") or "").casefold()
    if not precision:
        return "unknown_precision"
    if any(marker in precision for marker in COARSE_MARKERS):
        return "coarse_position"
    return "not_flagged_as_coarse"


def analyze(data):
    venues, events = validate_catalogue(data)
    occurrence = collections.Counter(e["venueId"] for e in events)
    rows = []
    for v in venues:
        rows.append({
            "venueId": v["id"], "name": v.get("name"),
            "city": v.get("city"), "region": v.get("region"),
            "concertsAffected": occurrence[v["id"]],
            "status": geo_status(v),
            "geoPrecision": v.get("geoPrecision"),
            "geoSource": v.get("geoSource"),
            "requiresReview": geo_status(v) != "not_flagged_as_coarse",
            "publicationAllowed": False,
        })
    rows.sort(key=lambda r: (
        not r["requiresReview"], -r["concertsAffected"],
        (r["city"] or "").casefold(), (r["name"] or "").casefold()
    ))
    counts = dict(collections.Counter(r["status"] for r in rows))
    uncertain = [r for r in rows if r["requiresReview"]]
    return {
        "schema": "grossesondes.concert.geo-audit.v1",
        "source": CATALOGUE_URL,
        "catalogueUpdatedAt": data.get("updatedAt"),
        "concerts": len(events),
        "venues": len(venues),
        "statusCounts": counts,
        "venuesToReview": len(uncertain),
        "concertsWithVenuesToReview": sum(r["concertsAffected"] for r in uncertain),
        "publishesNothing": True,
        "warning": "Un repère non signalé comme approximatif n'est pas une géolocalisation certifiée.",
        "venues": rows,
    }


def save(output, report):
    output.mkdir(parents=True, exist_ok=True)
    payload = dict(report, generatedAt=dt.datetime.now(dt.timezone.utc).isoformat())
    (output / "geopins_audit.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Grosses Ondes — audit cartographique Concerts", "",
        "**Diagnostic privé, sans modification du catalogue ni publication.**", "",
        f"Catalogue : {report['concerts']} concerts et {report['venues']} salles.",
        f"Salles à vérifier : {report['venuesToReview']}.",
        f"Concerts associés à ces salles : {report['concertsWithVenuesToReview']}.", "",
        "## Salles prioritaires", "",
    ]
    for venue in (v for v in report["venues"] if v["requiresReview"]):
        lines.append(
            f"- {venue['name']} ({venue['city']}) — "
            f"{venue['concertsAffected']} concert(s) — {venue['status']} — "
            f"{venue['geoPrecision'] or 'précision inconnue'}"
        )
    lines.extend(("", report["warning"], "Toute correction exige une adresse officielle, "
                 "un point géographique sourcé et une approbation indépendante."))
    (output / "RAPPORT_GEO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = analyze(load_live_catalogue())
    save(Path(args.output), report)
    print(
        "Audit géographique :", report["venuesToReview"], "salles à revoir ;",
        report["concertsWithVenuesToReview"], "concerts associés. Lecture seule."
    )


if __name__ == "__main__":
    main()
