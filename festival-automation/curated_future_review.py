"""Build private editorial research dossiers, never public festival rows.

Curated hints and observed first-party HTML are not organizer verification.
The output is deliberately NOT a public catalogue patch, and contains no
showOnMap, lineup, pricing, officialSite or authorized publication fields.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from curated_future_lead_watch import load_leads, published_duplicate, PRIVATE_STATUS
from official_watch import get_json, PAGES, GIT

SCHEMA = "grossesondes.curated-future-editorial-review.v1"
MAX_ROWS = 5
MAX_PRIMARY_AGE_DAYS = 7
MISSING_EDITORIAL_CHECKS = [
    "independent_date_corroboration",
    "organizer_identity",
    "official_home_ownership",
    "venue_for_2027",
    "lineup_if_announced",
    "ticketing_status_if_announced",
    "geographic_coordinates",
    "editorial_signoff",
]


def valid_observation(lead, value, today):
    """Untrusted intake cannot turn arbitrary claims into review evidence."""
    if (not isinstance(value, dict) or
            value.get("status") != PRIVATE_STATUS or
            value.get("publication_authorized") is not False or
            value.get("claim") != [
                lead["name"], lead["start_date"], lead["end_date"],
                lead["date_phrase"], lead["source_url"]]):
        return False
    try:
        first = date.fromisoformat(value["firstSeen"])
        last = date.fromisoformat(value["lastSeen"])
        now = date.fromisoformat(today)
    except (KeyError, TypeError, ValueError):
        return False
    digest = value.get("lastVisibleDigest")
    return (first <= last <= now
            and (now - last).days <= MAX_PRIMARY_AGE_DAYS
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)


def build_dossiers(leads, state, published, today):
    """Separate research hints, observed assertions and editorial validation."""
    if (not isinstance(leads, list) or len(leads) > MAX_ROWS or
            not isinstance(state, dict) or
            state.get("schema") != "grossesondes.source-watch.v1" or
            not isinstance(published, dict) or
            not isinstance(published.get("festivals"), list)):
        raise ValueError("dossier éditorial non conforme")
    current = date.fromisoformat(today)
    observations = state.get("curated_future_lead_observations", {})
    if not isinstance(observations, dict):
        raise ValueError("état d'observations invalide")
    dossiers = []
    proposals = []
    seen = set()
    for lead in leads:
        key = lead["id"]
        if key in seen:
            raise ValueError("identité dupliquée")
        seen.add(key)
        previous = observations.get(key)
        has_primary = valid_observation(lead, previous, today)
        duplicate = published_duplicate(lead, published)
        dated = lead["start_date"] is not None
        if duplicate:
            status = "ALREADY_IN_PUBLIC_CATALOGUE"
        elif not has_primary:
            status = "PRIMARY_RECHECK_PENDING"
        elif not dated:
            status = "PRIMARY_SEEN_DATE_UNANNOUNCED"
        elif previous["firstSeen"] == previous["lastSeen"]:
            status = "PRIMARY_SEEN_ONCE"
        else:
            status = "PRIMARY_SEEN_ON_SEPARATE_DAYS"
        # Always use *_hint, never publish-ready startDate/city/venue.
        dossiers.append({
            "id": key,
            "name_hint": lead["name"],
            "candidate_status": status,
            "genre_hint": lead["genre_hint"],
            "city_hint": lead["city_hint"],
            "region_hint": lead["region_hint"],
            "start_date_hint": lead["start_date"],
            "end_date_hint": lead["end_date"],
            "date_phrase_hint": lead["date_phrase"],
            "primary_source_url": lead["source_url"],
            "official_home_candidate_unverified": lead["official_home_candidate"],
            "source_observed": has_primary,
            "first_primary_observed": previous["firstSeen"] if has_primary else None,
            "last_primary_observed": previous["lastSeen"] if has_primary else None,
            "primary_text_sha256": previous["lastVisibleDigest"] if has_primary else None,
            "already_in_public_catalogue": duplicate,
            "exact_dates_known_in_research_hint": dated,
            "organizer_identity_verified": False,
            "venue_for_edition_verified": False,
            "independent_date_confirmation": False,
            "lineup_verified": False,
            "ticketing_verified": False,
            "coordinates_verified": False,
            "editorial_review_required": True,
            "publication_authorized": False,
            "notes": ("Recherche à partir de sources du festival : les indices ci-dessus "
                      "ne constituent pas une fiche publiable. Confirmer séparément "
                      "dates, édition, pertinence, organisateur, lieu et doublons."),
        })
        # A private candidate can be prepared from *one* confirmed visible
        # first-party date; it is NEVER an approved or public-facing row.
        if (has_primary and dated and not duplicate
                and date.fromisoformat(lead["start_date"]) > current):
            proposals.append({
                "id": key,
                "status": "PROPOSED_UNVERIFIED_EDITION",
                "review_only": True,
                "publication_authorized": False,
                "safe_to_publish": False,
                "primary_source": lead["source_url"],
                "observation_first": previous["firstSeen"],
                "observation_last": previous["lastSeen"],
                "independent_confirmation": False,
                "missing_checks": list(MISSING_EDITORIAL_CHECKS),
                "candidate_fields": {
                    "slug": key,
                    "name": lead["name"],
                    "startDate": lead["start_date"],
                    "endDate": lead["end_date"],
                    "city": None,
                    "department": None,
                    "region": None,
                    "venue": None,
                    "styles": None,
                    "bands": None,
                    "lineup": None,
                    "price": None,
                    "officialSite": None,
                    "lat": None,
                    "lon": None,
                    "showOnMap": False,
                    "futureVenueConfirmed": False,
                    "source": lead["source_url"],
                    "verificationStatus": (
                        "Brouillon privé ; une annonce primaire observée, "
                        "lieu/organisateur/indépendance non certifiés"),
                },
            })
    return {
        "schema": SCHEMA,
        "as_of": current.isoformat(),
        "safe_to_publish": False,
        "public_catalogue_editions_at_review": len(published["festivals"]),
        "total": len(dossiers),
        "source_seen_count": sum(row["source_observed"] for row in dossiers),
        "dated_hint_count": sum(row["exact_dates_known_in_research_hint"]
                                for row in dossiers),
        "publication_authorized_count": 0,
        "proposal_count_review_only": len(proposals),
        "proposed_additions_review_only": proposals,
        "dossiers": dossiers,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    config = json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8"))
    leads = load_leads(config)
    pages, git = get_json(PAGES), get_json(GIT)
    if pages != git:
        raise ValueError("catalogues GitHub et Pages divergents : dossiers bloques")
    state = json.loads((args.intake / "source-watch-state.json").read_text(
        encoding="utf-8"))
    review = build_dossiers(leads, state, git, today)
    output = args.intake / "curated-future-review.json"
    output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if (report.get("schema") != "grossesondes.source-watch-report.v1"
            or report.get("date") != today):
        raise ValueError("rapport d'exécution non conforme")
    report["curated_future_editorial_dossiers_private"] = review["total"]
    report["curated_future_editorial_sources_seen_private"] = review["source_seen_count"]
    report["curated_future_editorial_proposals_private"] = review["proposal_count_review_only"]
    report["curated_future_editorial_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("DOSSIERS_FESTIVALS_2027:", json.dumps({
        "total": review["total"],
        "primary_observed": review["source_seen_count"],
        "exact_dates_as_hints": review["dated_hint_count"],
        "proposals_review_only": review["proposal_count_review_only"],
        "statuses": {d["id"]: d["candidate_status"] for d in review["dossiers"]},
        "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
