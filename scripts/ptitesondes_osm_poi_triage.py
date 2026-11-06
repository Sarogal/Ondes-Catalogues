#!/usr/bin/env python3
"""Bounded OSM object-ID hints for six verified municipal pages, PRIVATE ONLY.

The script is public code, but it consumes the PRIVATE backlog only inside a
public GitHub runner and writes findings to the PRIVATE intake branch. No
coordinates, secret, raw page, address or unverified proposal is published.
Object IDs are never proof of an entrance, or permission to publish.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

SCHEMA = "ptitesondes.place_osm_poi_triage.v1"
MUNICIPAL_SCHEMA = "ptitesondes.municipal_source_probe.v1"
MAX_BYTES = 200_000
MAX_ELEMENTS = 120
MAX_RESULTS = 20
MAX_PER_DAY = 2
MAX_RECORDS = 4000
ENDPOINTS = (
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# Explicit administrative INSEE codes. The three-digit postal prefix is not
# used to locate a venue; the code and postcode are only mismatch checks.
PINS = {
    "Cagnes-sur-Mer": ("LUDOTHEQUE MUNICIPALE", "06027", "06800",
        "https://ludotheque.cagnes.fr/ludotheque/informations-editeur.aspx"),
    "Cossé-le-Vivien": ("CC CRAON - Médiathèque-Ludothèque de Cossé-le-Vivien",
        "53077", "53230",
        "https://www.cosse-le-vivien.fr/mairie-cosse/tellement-locale/equipements/mediatheque"),
    "Craon": ("CC CRAON - Médiathèque-ludothèque de Craon", "53084", "53400",
        "https://www.ville-craon53.fr/mediatheque-intercommunale.aspx"),
    "Dax": ("BIBLIOTHEQUE-LUDOTHÈQUE MUNICIPALE DE DAX", "40088", "40100",
        "https://www.dax.fr/vivre-a-dax/culture/la-bibliotheque/"),
    "Renazé": ("CC CRAON Médiathèque-ludothèque de Renazé", "53188", "53800",
        "https://renaze53.fr/culture/mediatheque/"),
    "Saint-Jean": ("Médiathèque-Ludothèque", "31488", "31240",
        "https://www.mairie-saintjean.fr/mes-sorties-mes-loisirs/culture/mediatheque-ludotheque/"),
}


def norm(value):
    if not isinstance(value, str):
        return ""
    s = unicodedata.normalize("NFKD", value)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def key(city, venue):
    if not norm(city) or not norm(venue):
        return ""
    return norm(city) + "|" + norm(venue)


PINS_BY_KEY = {key(city, row[0]): (city, *row) for city, row in PINS.items()}
assert len(PINS_BY_KEY) == 6


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def overpass_query(code):
    if code not in {v[1] for v in PINS.values()}:
        raise ValueError("Commune non épinglée")
    return (
        '[out:json][timeout:20];'
        'area["ref:INSEE"="' + code +
        '"]["boundary"="administrative"]["admin_level"="8"]->.target;'
        '(nwr["amenity"="toy_library"](area.target);'
        'nwr["amenity"="library"](area.target););'
        'out tags ' + str(MAX_ELEMENTS) + ';'
    )


def fetch(endpoint, code):
    if endpoint not in ENDPOINTS:
        raise ValueError("Instance Overpass non autorisée")
    url = endpoint + "?" + urlencode({"data": overpass_query(code)})
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != urlsplit(endpoint).hostname
            or parsed.path != "/api/interpreter" or parsed.port not in (None, 443)):
        raise ValueError("URL Overpass non conforme")
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PtitesOndes-OSMPrivateObjectTriage/1.0 (bounded; read-only)",
    })
    with build_opener(NoRedirect()).open(req, timeout=27) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Overpass status ou redirection refusée")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Overpass trop volumineux ou vide")
    return json.loads(raw.decode("utf-8-sig"))


def candidates(response, city, postcode):
    """Keep only IDs and safe tag-presence flags. No GPS and no addresses."""
    if (not isinstance(response, dict)
            or not isinstance(response.get("elements"), list)
            or response.get("remark")
            or len(response["elements"]) >= MAX_ELEMENTS):
        raise ValueError("Overpass incomplet")
    result, seen = [], set()
    for el in response["elements"]:
        if not isinstance(el, dict):
            continue
        kind, oid, tags = el.get("type"), el.get("id"), el.get("tags")
        if (kind not in ("node", "way", "relation")
                or type(oid) is not int or oid <= 0
                or not isinstance(tags, dict)
                or tags.get("amenity") not in ("library", "toy_library")):
            continue
        name = tags.get("name")
        if not isinstance(name, str) or not 4 <= len(name) <= 140:
            continue
        if tags["amenity"] == "library" and not any(
            part in norm(name) for part in
            ("ludotheque", "mediatheque", "jeunesse", "espace jeux")):
            continue
        if (tags.get("addr:city") and norm(tags.get("addr:city")) != norm(city)
                or tags.get("addr:postcode") and tags.get("addr:postcode") != postcode):
            continue
        object_id = f"{kind}/{oid}"
        if object_id in seen:
            continue
        seen.add(object_id)
        result.append({
            "osm_object_hint": object_id,
            "osm_url_hint": f"https://www.openstreetmap.org/{object_id}",
            "mapped_name_unverified": name,
            "mapped_amenity_unverified": tags["amenity"],
            "post_code_tag_matches": tags.get("addr:postcode") == postcode,
            "city_tag_matches": norm(tags.get("addr:city")) == norm(city),
            "street_tag_present": bool(tags.get("addr:street")),
            "house_number_tag_present": bool(tags.get("addr:housenumber")),
            "mapped_feature_verified": False, "gps_verified": False,
        })
    if len(result) > MAX_RESULTS:
        raise ValueError("Trop de candidats pour une sélection sûre")
    return sorted(result, key=lambda v: v["osm_object_hint"])


def validate_inputs(municipal, backlog, existing):
    if (not isinstance(municipal, dict)
            or municipal.get("schema") != MUNICIPAL_SCHEMA
            or municipal.get("safe_to_publish") is not False
            or municipal.get("proposals") != []
            or not isinstance(municipal.get("records"), list)
            or len(municipal["records"]) > 6
            or not isinstance(backlog, list) or len(backlog) > MAX_RECORDS):
        raise ValueError("Rapport municipal ou backlog invalide")
    index = {}
    for entry in backlog:
        if not isinstance(entry, dict):
            raise ValueError("Candidat privé non structuré")
        k = key(entry.get("city"), entry.get("venue"))
        if not k or k in index:
            raise ValueError("Doublon ou identité privée ambiguë")
        index[k] = entry
    checked = {}
    for item in municipal["records"]:
        if not isinstance(item, dict):
            raise ValueError("Ligne municipale invalide")
        k = key(item.get("city"), item.get("venue"))
        if (k not in PINS_BY_KEY or k in checked or k not in index
                or item.get("public_eligible") is not False
                or item.get("gps_verified") is not False
                or item.get("official_site_verified") is not False
                or item.get("pinned_current_source") != PINS_BY_KEY[k][4]):
            raise ValueError("Source municipale non épinglée ou ambiguë")
        lead = index[k]
        if (lead.get("status") != "review_required"
                or lead.get("public_eligible") is not False
                or lead.get("gps_verified") is not False
                or lead.get("official_site_verified") is not False
                or not isinstance(lead.get("evidence"), list)):
            raise ValueError("Permission privée incorrecte")
        postcodes = {
            evidence.get("historic_postcode_hint_unverified")
            for evidence in lead["evidence"]
            if isinstance(evidence, dict)
            and evidence.get("from") == "ministere-bibliotheques-index"
        }
        if postcodes != {PINS_BY_KEY[k][3]}:
            raise ValueError("Code postal historique incompatible")
        checked[k] = item

    old = {}
    if existing is not None:
        if (not isinstance(existing, dict) or existing.get("schema") != SCHEMA
                or existing.get("safe_to_publish") is not False
                or existing.get("proposals") != []
                or not isinstance(existing.get("records"), list)
                or len(existing["records"]) > 6):
            raise ValueError("Ancien rapport OSM non sûr")
        for item in existing["records"]:
            if not isinstance(item, dict):
                raise ValueError("Ancienne ligne OSM invalide")
            k = key(item.get("city"), item.get("venue"))
            if (k not in PINS_BY_KEY or k in old
                    or item.get("public_eligible") is not False
                    or item.get("gps_verified") is not False
                    or item.get("official_site_verified") is not False
                    or item.get("mapped_feature_verified") is not False
                    or set(item) - {
                        "city", "venue", "commune_insee", "status",
                        "osm_candidates_unverified", "public_eligible",
                        "mapped_feature_verified", "official_site_verified",
                        "gps_verified", "observed_at", "source_errors"}):
                raise ValueError("Ancienne preuve OSM non sûre")
            if (item.get("commune_insee") != PINS_BY_KEY[k][2]
                    or not isinstance(item.get("osm_candidates_unverified"), list)
                    or len(item["osm_candidates_unverified"]) > MAX_RESULTS):
                raise ValueError("Ancien objet OSM non sûr")
            fields = {"osm_object_hint", "osm_url_hint",
                      "mapped_name_unverified", "mapped_amenity_unverified",
                      "post_code_tag_matches", "city_tag_matches",
                      "street_tag_present", "house_number_tag_present",
                      "mapped_feature_verified", "gps_verified"}
            for hint in item["osm_candidates_unverified"]:
                if (not isinstance(hint, dict) or set(hint) != fields
                        or hint.get("mapped_feature_verified") is not False
                        or hint.get("gps_verified") is not False
                        or not isinstance(hint.get("osm_object_hint"), str)
                        or not re.fullmatch(r"(?:node|way|relation)/[1-9][0-9]*",
                                            hint["osm_object_hint"])
                        or hint.get("osm_url_hint") !=
                        "https://www.openstreetmap.org/" + hint["osm_object_hint"]):
                    raise ValueError("Indices OSM précédents non sûrs")
            old[k] = item
    return checked, old


def audit(municipal, backlog, previous, today, get=fetch):
    if not isinstance(today, date):
        raise ValueError("Date invalide")
    checked, old = validate_inputs(municipal, backlog, previous)
    # Two communes per scheduled day; complete six-town rotation in 3 days.
    keys = sorted(checked)
    start = (today.toordinal() * MAX_PER_DAY) % len(keys) if keys else 0
    today_keys = {keys[(start + i) % len(keys)]
                  for i in range(min(MAX_PER_DAY, len(keys)))} if keys else set()
    records, requests = [], 0
    for k in keys:
        municipal_row = checked[k]
        city, venue, code, _, _ = PINS_BY_KEY[k]
        row = {
            "city": city, "venue": venue, "commune_insee": code,
            "status": "municipal_source_not_confirmed",
            "osm_candidates_unverified": [],
            "public_eligible": False, "mapped_feature_verified": False,
            "official_site_verified": False, "gps_verified": False,
        }
        if municipal_row.get("status") != "current_municipal_page_mentions_place_private_only":
            records.append(row)
            continue
        if k not in today_keys:
            prior = old.get(k)
            if (prior and prior.get("status") in (
                "single_osm_object_hint_requires_exact_proof",
                "multiple_osm_objects_require_manual_selection",
                "no_named_osm_amenity_found_in_index")
                    and prior.get("observed_at") and
                    (today - date.fromisoformat(prior["observed_at"])).days in range(0, 11)):
                row["status"] = prior["status"]
                row["osm_candidates_unverified"] = prior["osm_candidates_unverified"]
                row["observed_at"] = prior["observed_at"]
            else:
                row["status"] = "not_scanned_yet_or_stale"
            records.append(row)
            continue
        row["observed_at"] = today.isoformat()
        errors = []
        for endpoint in ENDPOINTS:
            try:
                requests += 1
                response = get(endpoint, code)
                if len(json.dumps(response, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
                    raise ValueError("Réponse OSM surdimensionnée")
                hints = candidates(response, city, PINS_BY_KEY[k][3])
                row["osm_candidates_unverified"] = hints
                if not hints:
                    row["status"] = "no_named_osm_amenity_found_in_index"
                elif len(hints) == 1:
                    row["status"] = "single_osm_object_hint_requires_exact_proof"
                else:
                    row["status"] = "multiple_osm_objects_require_manual_selection"
                break
            except (OSError, ValueError, UnicodeError, TypeError) as exc:
                errors.append(type(exc).__name__)
        else:
            row["status"] = "osm_index_unavailable_or_incomplete"
            row["source_errors"] = errors
        records.append(row)
    counts = {}
    for item in records:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    report = {"schema": SCHEMA, "observed_at": today.isoformat(),
              "safe_to_publish": False, "proposals": [], "publications": 0,
              "records": records}
    summary = {"date": today.isoformat(), "candidates": len(records),
               "queries_attempted": requests, "status_counts": counts,
               "published": 0, "mode": "private_osm_hint_only"}
    return report, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--municipal", type=Path, required=True)
    parser.add_argument("--backlog", type=Path, required=True)
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    municipal = json.loads(args.municipal.read_text(encoding="utf-8"))
    backlog = json.loads(args.backlog.read_text(encoding="utf-8"))
    existing = (json.loads(args.existing.read_text(encoding="utf-8"))
                if args.existing and args.existing.exists() else None)
    report, summary = audit(municipal, backlog, existing, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
