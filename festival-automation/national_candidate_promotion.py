"""Fail-closed national festival promotion preflight (PRIVATE output only).

A national lead is not publication authority. Exact first-party pages must be
re-fetched from a code-reviewed allowlist; historic editions are collision hints
only. No catalogue, patch or approval file is written by this module.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
import unicodedata
from map_reference import (
    assess_mozhell_organizer_maps, MOZHELL_ACCESS_FR, MOZHELL_ACCESS_EN,
)

SCHEMA = "grossesondes.national-candidate-promotion-private.v1"
EDITORIAL_SCHEMA = "grossesondes.national-editorial-reconciliation-private.v1"

# Curated first-party source registry: NEVER take network destinations from a
# private dossier, a discovered URL, an archive, or an external JSON.
APPROVED = {
    "mozhell-open-air-2027": {
        "dossier_name": "MozHell Open Air",
        "year": 2027, "region": "Grand Est", "city": "Insming",
        "department": "57", "start": "2027-07-23", "end": "2027-07-25",
        "dates_url": "https://www.mozhell.fr/fr/le-mozhell-est-de-retour-pour-une-nouvelle-edition-en-2027",
        "lineup_url": "https://www.mozhell.fr/fr/3-groupes-annonces-et-billetterie-ouverte",
        "organizer_url": "https://www.mozhell.fr/fr/association-mozhell-prod",
        "organizer": "MOZHELL PROD",
        "bands": ["Ultra Vomit", "THE ARRS", "LocoMuerte"],
        # Exact reviewed 2027 pages. Press agreement is NOT source independence.
        "locality_url": "https://www.mozhell.fr/fr/devenir-exposant",
        "press_url": "https://www.hardrockmag.fr/mozhell-open-air-2027-trois-premiers-groupes-devoiles/",
        "access_fr_url": MOZHELL_ACCESS_FR,
        "access_en_url": MOZHELL_ACCESS_EN,
    }
}

BASE_BLOCKERS = [
    "independent_date_confirmation",
    "edition_2027_venue_confirmation",
    "venue_coordinates_confirmation",
    "editorial_signoff",
    "publication_sync_gate_not_connected",
]


def normalized(value):
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _source_fetch(url):
    # Reuse the hardened same-domain redirect and HTML-to-visible-text
    # validator already used by the trusted public publication workflow.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from grossesondes_stage import official_text
    return official_text(url, registered=True, raw=False)


def _source_fetch_html(url):
    # The official organizer page itself is the anchor of the Google Maps
    # reference. We do not contact Maps, accept freeform URLs or geocode.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from grossesondes_stage import official_text
    return official_text(url, registered=True, raw=True)


def _private_candidate_preview(spec, entry, maps, today):
    """Complete proposal to inspect, never a publishable approval/patch.

    The map coordinates are a linked POI reference. The public map flag stays
    off until a distinct publication gate revalidates the *2027* site.
    """
    if (entry.get("status") != "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE"
            or not isinstance(maps, dict)
            or maps.get("status") != "ORGANIZER_LINKED_MAPS_POI_REVIEW_ONLY"):
        return None
    fields = entry["verified_fields_private"]
    return {
        "schema": "grossesondes.national-festival-preview-private.v1",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False,
        "publication_ready": False,
        "map_reference_is_future_venue_proof": False,
        "candidate": {
            "slug": "mozhell-open-air-2027",
            "name": fields["name"],
            "startDate": fields["startDate"],
            "endDate": fields["endDate"],
            "city": fields["city"], "department": fields["department"],
            "region": fields["region"],
            "venue": None,
            "styles": "Metal / Rock",
            "bands": fields["bands"], "days": "3",
            "capacity": None, "price": None,
            "organizer": fields["organizer"],
            "officialSite": "https://www.mozhell.fr/fr/",
            "social": None,
            "status": "Annoncé",
            "source": spec["dates_url"],
            "lastVerified": today,
            "notes": (
                "Du 23 au 25 juillet 2027 à Insming ; trois premiers "
                "groupes annoncés. Repère Google Maps relié au site officiel ; "
                "les pages FR/EN divergent (5 et 13 rue de l'Albe). "
                "Emplacement exact 2027 à confirmer, programmation incomplète."
            ),
            "lat": maps["coordinates"]["lat"],
            "lon": maps["coordinates"]["lon"],
            "geoPrecision": "commune",
            "geoCity": "Insming",
            "geoSource": maps["maps_url"],
            "futureVenueConfirmed": False,
            "showOnMap": False,
            "dateRangeIsContinuous": True,
            "sourceConfidence": "organisateur (dates/artistes, lieu en revue)",
            "verificationStatus": (
                "Édition datée ; repère Maps organisateur à confirmer pour 2027"
            ),
            "lineup": list(fields["lineup"]),
            "auditSources": [
                spec["dates_url"], spec["lineup_url"], spec["locality_url"],
                spec["access_fr_url"], spec["access_en_url"],
            ],
        },
    }


def _collision(dossier, spec, published, history):
    name = normalized(spec["dossier_name"])
    year = str(spec["year"])
    for row in published.get("festivals", []):
        title = normalized(row.get("name", ""))
        slug = row.get("slug", "")
        if (year in title.split() and name in title) or slug == "mozhell-open-air-2027":
            return "already_published_or_duplicate"
    for row in history.get("knownFestivals", []):
        if (row.get("lastKnownYear") == spec["year"]
                and normalized(row.get("name", "")) == name):
            return "historical_same_year_needs_review"
    if (dossier.get("published_exact_edition_matches")
            or dossier.get("published_city_conflicts")
            or dossier.get("published_title_city_variants_review_only")):
        return "reconciliation_collision"
    return None


def build_review(editorial, published, history, today, fetcher=None, html_fetcher=None):
    if (not isinstance(editorial, dict)
            or editorial.get("schema") != EDITORIAL_SCHEMA
            or editorial.get("review_only") is not True
            or editorial.get("publication_authorized") is not False
            or editorial.get("safe_to_publish") is not False
            or not isinstance(editorial.get("dossiers"), list)
            or published.get("schema") != 1
            or not isinstance(published.get("festivals"), list)
            or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Input schemas or private fail-closed flags invalid")
    today_date = date.fromisoformat(today)
    fetch = fetcher or _source_fetch
    fetch_html = html_fetcher or _source_fetch_html
    rows = []
    for dossier in editorial["dossiers"]:
        if not isinstance(dossier, dict) or not isinstance(dossier.get("id"), str):
            raise ValueError("Malformed editorial dossier")
        entry = {
            "id": dossier["id"], "name_hint": dossier.get("name_hint"),
            "edition_year_hint": dossier.get("edition_year_hint"),
            "status": "RESEARCH_REQUIRED",
            "publication_authorized": False, "safe_to_publish": False,
            "review_only": True, "verified_fields_private": {},
            "checked_official_urls": [],
            "missing_checks": sorted(set(dossier.get("missing_checks", [])) |
                                     set(BASE_BLOCKERS)),
        }
        spec = next((s for s in APPROVED.values()
                     if normalized(dossier.get("name_hint", "")) ==
                     normalized(s["dossier_name"])
                     and dossier.get("edition_year_hint") == s["year"]
                     and dossier.get("region_hint") == s["region"]), None)
        if spec is None:
            rows.append(entry)
            continue
        primary = dossier.get("primary_observation")
        if (dossier.get("city_hint") != spec["city"]
                or not isinstance(primary, dict)
                or primary.get("source_url") != spec["dates_url"]
                or primary.get("dates_visible_in_primary") is not True
                or primary.get("start_date_hint") != spec["start"]
                or primary.get("end_date_hint") != spec["end"]
                or primary.get("publication_authorized") is not False
                or dossier.get("review_only") is not True
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False):
            entry["status"] = "PRIMARY_EVIDENCE_MISMATCH"
            rows.append(entry)
            continue
        collision = _collision(dossier, spec, published, history)
        if collision:
            entry["status"] = "DUPLICATE_OR_CONFLICT"
            entry["missing_checks"].append(collision)
            entry["missing_checks"] = sorted(set(entry["missing_checks"]))
            rows.append(entry)
            continue
        try:
            body_dates = normalized(fetch(spec["dates_url"]))
            body_lineup = normalized(fetch(spec["lineup_url"]))
            body_organizer = normalized(fetch(spec["organizer_url"]))
        except Exception:
            # No exception contents in private report or public action logs:
            # upstream responses may contain secrets or arbitrary text.
            entry["status"] = "OFFICIAL_RECHECK_FAILED"
            rows.append(entry)
            continue
        entry["checked_official_urls"] = [spec["dates_url"], spec["lineup_url"],
                                          spec["organizer_url"]]
        if (normalized("23, 24 et 25 juillet 2027") not in body_dates
                or normalized("Insming") not in body_dates
                or normalized("MozHell Open Air") not in body_dates
                or not all(normalized(b) in body_lineup for b in spec["bands"])
                or normalized("2027") not in body_lineup
                or normalized("Association MOZHELL PROD") not in body_organizer
                or not date.fromisoformat(spec["start"]) > today_date):
            entry["status"] = "OFFICIAL_CLAIMS_NOT_RECONFIRMED"
            rows.append(entry)
            continue
        entry["status"] = "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE"
        entry["verified_fields_private"] = {
            "name": spec["dossier_name"] + " " + str(spec["year"]),
            "startDate": spec["start"], "endDate": spec["end"],
            "city": spec["city"], "department": spec["department"],
            "region": spec["region"], "organizer": spec["organizer"],
            "lineup": list(spec["bands"]), "bands": len(spec["bands"]),
        }
        # The organizer's three pages are NOT independent corroborations.
        # Neither an address from a prior edition nor city-centroid GPS is
        # automatically a proven location for the 2027 event.
        # Distinguish organizer location wording from an exact 2027 venue.
        # A media article that repeats a press release cannot prove independence.
        crosscheck = {
            "organizer_2027_locality": "NOT_RECHECKED",
            "exact_2027_venue_verified": False,
            "press_agreement": "NOT_RECHECKED",
            "press_independence_verified": False,
        }
        try:
            locality = normalized(fetch(spec["locality_url"]))
            entry["checked_official_urls"].append(spec["locality_url"])
            if (normalized("au cœur du village d'Insming") in locality
                    and normalized("23 24 et 25 juillet 2027") in locality):
                crosscheck["organizer_2027_locality"] = "INSMING_VILLAGE_ONLY"
            else:
                crosscheck["organizer_2027_locality"] = "CLAIM_NOT_RECONFIRMED"
        except Exception:
            crosscheck["organizer_2027_locality"] = "SOURCE_UNAVAILABLE"
        try:
            press = normalized(fetch(spec["press_url"]))
            entry["checked_external_urls_private"] = [spec["press_url"]]
            if (normalized("MozHell Open Air 2027") in press
                    and normalized("23 au 25 juillet") in press
                    and normalized("Insming") in press
                    and all(normalized(b) in press for b in spec["bands"])):
                crosscheck["press_agreement"] = "SAME_CLAIMS_PROVENANCE_UNVERIFIED"
            else:
                crosscheck["press_agreement"] = "CLAIM_NOT_RECONFIRMED"
        except Exception:
            crosscheck["press_agreement"] = "SOURCE_UNAVAILABLE"
        entry["crosschecks_private"] = crosscheck
        try:
            fr_html = fetch_html(spec["access_fr_url"])
            en_html = fetch_html(spec["access_en_url"])
            maps = assess_mozhell_organizer_maps(fr_html, en_html)
        except Exception:
            # Failure must never be turned into a favorable location claim.
            maps = None
        entry["map_reference_private"] = maps or {
            "status": "MAPS_REFERENCE_UNCONFIRMED",
            "publication_authorized": False,
        }
        if maps:
            entry["checked_official_urls"].extend([
                spec["access_fr_url"], spec["access_en_url"],
            ])
            entry["candidate_preview_private"] = _private_candidate_preview(
                spec, entry, maps, today
            )
        # Even both positive crosschecks must never remove these blockers.
        entry["missing_checks"] = sorted(set(BASE_BLOCKERS))
        rows.append(entry)
    return {
        "schema": SCHEMA, "as_of": today, "source_review_as_of": editorial.get("as_of"),
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "public_editions_count": len(published["festivals"]),
        "dossiers_total": len(rows),
        "first_party_rechecked_count": sum(
            e["status"] == "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE" for e in rows),
        "dossiers": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--history", required=True)
    args = parser.parse_args()
    intake = Path(args.intake)
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    editorial = read(intake / "national-festival-editorial-review.json")
    public = read(args.catalog)
    history = read(args.history)
    # Use Paris time; the publication date cannot be guessed from a lead.
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    result = build_review(editorial, public, history, today)
    output = intake / "national-festival-candidate-review.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("Contrôle de promotion privé terminé; aucune publication autorisée.")


if __name__ == "__main__":
    main()
