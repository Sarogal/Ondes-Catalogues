"""Pure, private editorial reconciliation of national festival discoveries.

Crosschecks historic names, published editions and fresh vetted observations.
A historic edition is NEVER evidence of the next year's edition. No network
fetch destinations are drawn from state or queues. No catalogue writer exists.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from curated_future_lead_watch import load_leads
from curated_future_review import valid_observation
from national_discovery_queue import _identity, _safe_title, SCHEMA as QUEUE_SCHEMA
from national_detail_qualification import (
    SCHEMA as DETAIL_SCHEMA, _valid_observation,
)
from official_watch import get_json, PAGES, GIT
from regional_festival_discovery import HISTORY_PAGES, HISTORY_GIT

SCHEMA = "grossesondes.national-editorial-reconciliation-private.v1"
MAX_PUBLIC = 600
MAX_ARCHIVE = 500
MAX_QUEUE = 200
MAX_SOURCE_ROWS = 12
MAX_MATCHES = 8


def _canonical(value):
    """Exact normalized name excluding the edition year; never fuzzy matching."""
    if not _safe_title(value):
        return None
    result = _identity(value)
    return result[0] if result else None


def _names(row):
    names = [row.get("name")]
    extra = row.get("aliases", [])
    if isinstance(extra, list) and len(extra) <= 25:
        names.extend(extra)
    return {name for value in names if (name := _canonical(value))}


def _city_equal(a, b):
    from source_qualification import normalized
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    if not a.strip() or not b.strip():
        return None
    return normalized(a) == normalized(b)


def _archive_matches(dossier, history):
    """History provides identity hints, not evidence that an edition exists."""
    found = []
    names = {dossier["normalized_name"]}
    names.update(filter(None, (_canonical(v) for v in dossier.get("name_variants", [])[:8])))
    for row in history:
        if not isinstance(row, dict) or row.get("region") != dossier["region_hint"]:
            continue
        if type(row.get("lastKnownYear")) is not int:
            continue
        if not names.intersection(_names(row)):
            continue
        city = _city_equal(dossier.get("city_hint"), row.get("city"))
        if city is False:
            continue
        try:
            start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
            if start > end or end.year != row["lastKnownYear"]:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        # No archive 2027 name may be silently reinterpreted as evidence
        # of an earlier or later edition.
        if (dossier["edition_year_hint"] is not None
                and row["lastKnownYear"] >= dossier["edition_year_hint"]):
            continue
        found.append({
            "slug": row.get("slug") if isinstance(row.get("slug"), str) else None,
            "last_known_year": row["lastKnownYear"],
            "city_hint_match": city is True,
            "identity_match_only": True,
            "future_edition_verified": False,
        })
    return found[:MAX_MATCHES]


def _public_matches(dossier, published):
    exact, uncertain = [], []
    names = {dossier["normalized_name"]}
    names.update(filter(None, (_canonical(v) for v in dossier.get("name_variants", [])[:8])))
    edition = dossier.get("edition_year_hint")
    if type(edition) is not int:
        return exact, uncertain
    for row in published:
        if not isinstance(row, dict) or row.get("region") != dossier["region_hint"]:
            continue
        if not _names(row).intersection(names):
            continue
        try:
            start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        except (ValueError, TypeError, KeyError):
            continue
        if start.year != edition or end < start:
            continue
        city = _city_equal(dossier.get("city_hint"), row.get("city"))
        item = {
            "slug": row.get("slug") if isinstance(row.get("slug"), str) else None,
            "year": edition,
            "city_hint_match": city,
            "edition_already_published": True,
        }
        (uncertain if city is False else exact).append(item)
    return exact[:MAX_MATCHES], uncertain[:MAX_MATCHES]




def _uncovered_homepage_dates(dossier, hints, published):
    """Warn when a generic same-year public match may cover another edition.

    History can describe an event brand with winter *and* summer sessions
    during the same year. A matching name/year alone cannot prove that the
    distinct displayed dates have already been published. This only raises
    a private conflict; it never proposes a new public edition.
    """
    if not hints:
        return []
    target_names = {dossier["normalized_name"]}
    target_names.update(filter(
        None, (_canonical(x) for x in dossier.get("name_variants", [])[:8])))
    year = dossier.get("edition_year_hint")
    covered = set()
    for row in published:
        if (not isinstance(row, dict)
                or row.get("region") != dossier["region_hint"]
                or not _names(row).intersection(target_names)
                or _city_equal(dossier.get("city_hint"), row.get("city")) is False):
            continue
        try:
            start = date.fromisoformat(row["startDate"])
            end = date.fromisoformat(row["endDate"])
        except (ValueError, KeyError, TypeError):
            continue
        if start.year != year or end < start:
            continue
        covered.add((start.isoformat(), end.isoformat()))
    return [dict(x) for x in hints
            if (x["start_date_hint"], x["end_date_hint"]) not in covered]


def _published_city_variants(dossier, published):
    """Flag exact NAME — CITY variants as possible prior public editions.

    This is a *collision hint*, not a duplicate verdict. The suffix must
    equal the public record's own city and year/region must agree. A missing
    dossier city is NOT silently inferred from the municipal source.
    """
    names = {dossier["normalized_name"]}
    names.update(filter(None, (_canonical(v) for v in dossier.get("name_variants", [])[:8])))
    edition = dossier.get("edition_year_hint")
    if type(edition) is not int:
        return []
    found = []
    for row in published:
        if (not isinstance(row, dict) or row.get("region") != dossier["region_hint"]
                or not isinstance(row.get("name"), str)):
            continue
        parts = row["name"].split(" — ")
        if (len(parts) != 2 or _canonical(parts[0]) not in names
                or _city_equal(parts[1], row.get("city")) is not True
                or _city_equal(dossier.get("city_hint"), row.get("city")) is False):
            continue
        try:
            start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
        except (KeyError, ValueError, TypeError):
            continue
        if start.year != edition or end < start:
            continue
        found.append({
            "slug": row.get("slug") if isinstance(row.get("slug"), str) else None,
            "year": edition, "published_city": row["city"],
            "possible_same_edition_only": True,
            "edition_already_published": False,
            "publication_authorized": False,
        })
        if len(found) == MAX_MATCHES:
            break
    return found


def _dynamic_proofs(dossier, detail):
    """Recheck each detail report against the same dossier URL and identity."""
    rows = []
    witnesses = {
        (s["url"], s["discovered_via"])
        for s in dossier.get("sources", [])[:MAX_SOURCE_ROWS]
        if isinstance(s, dict) and s.get("kind") == "REGIONAL_INDEX_UNVERIFIED"
        and isinstance(s.get("url"), str)
        and isinstance(s.get("discovered_via"), str)
        and s.get("publication_authorized") is False
    }
    for record in detail.get("observations", [])[:MAX_QUEUE]:
        if not isinstance(record, dict):
            continue
        url, origin = record.get("candidate_url"), record.get("index_url")
        if (url, origin) not in witnesses:
            continue
        source = {
            "dossier_id": dossier["id"], "url": url,
            "index_url": origin, "title": record.get("name_hint"),
            "year": dossier["edition_year_hint"],
        }
        if (record.get("name_hint") not in dossier.get("name_variants", [])
                or not _valid_observation(source, record, detail["as_of"])):
            continue
        rows.append({
            "url": url, "index_url": origin,
            "observed_at": record["observed_at"],
            "name_seen": record["name_seen"],
            "edition_year_near_name": record["edition_year_near_name"],
            "possible_cancellation": record["possible_cancellation_review_only"],
            "visible_text_sha256": record["visible_text_sha256"],
            "structured_event_clues_private": [
                dict(item) for item in record.get("structured_event_clues_private", [])
            ],
            "official_site_verified": False,
            "independent_source_verified": False,
            "dates_verified": False,
        })
    return rows


def _primary_proof(dossier, leads, state, today):
    observations = state.get("curated_future_lead_observations", {})
    if not isinstance(observations, dict):
        raise ValueError("observations primaires incoherentes")
    for lead in leads:
        if (dossier.get("normalized_name") != _canonical(lead["name"])
                or dossier.get("region_hint") != lead["region_hint"]
                or dossier.get("edition_year_hint") !=
                    (int(lead["start_date"][:4]) if lead["start_date"] else
                     int(lead["id"][-4:]) if lead["id"][-4:].isdigit() else None)
                or not any(
                    s.get("kind") == "CURATED_PRIMARY_CANDIDATE"
                    and s.get("url") == lead["source_url"]
                    and s.get("publication_authorized") is False
                    for s in dossier.get("sources", []) if isinstance(s, dict))):
            continue
        row = observations.get(lead["id"])
        if valid_observation(lead, row, today):
            return {
                "curated_id": lead["id"],
                "source_url": lead["source_url"],
                "observed_at": row["lastSeen"],
                "first_seen": row["firstSeen"],
                "visible_text_sha256": row["lastVisibleDigest"],
                "dates_visible_in_primary": lead["start_date"] is not None,
                "start_date_hint": lead["start_date"],
                "end_date_hint": lead["end_date"],
                "organizer_verified": False,
                "independent_confirmation": False,
                "publication_authorized": False,
            }
    return None


def build_review(queue, detail, state, leads, public, history, today):
    date.fromisoformat(today)
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or queue.get("as_of") != today
            or queue.get("publication_authorized") is not False
            or queue.get("safe_to_publish") is not False
            or queue.get("review_only") is not True
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > MAX_QUEUE
            or not isinstance(detail, dict) or detail.get("schema") != DETAIL_SCHEMA
            or detail.get("as_of") != today or detail.get("publication_authorized") is not False
            or detail.get("safe_to_publish") is not False
            or not isinstance(detail.get("observations"), list)
            or not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or not isinstance(leads, list)
            or not isinstance(public, dict) or public.get("schema") != 1
            or not isinstance(public.get("festivals"), list)
            or len(public["festivals"]) > MAX_PUBLIC
            or not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or len(history["knownFestivals"]) > MAX_ARCHIVE):
        raise ValueError("donnees de reconciliation incompletes")
    result, proposed, seen = [], [], set()
    for dossier in queue["dossiers"]:
        if (not isinstance(dossier, dict)
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False
                or not isinstance(dossier.get("id"), str)
                or dossier["id"] in seen
                or not isinstance(dossier.get("normalized_name"), str)
                or not isinstance(dossier.get("region_hint"), str)
                or (dossier.get("edition_year_hint") is not None
                    and type(dossier.get("edition_year_hint")) is not int)
                or not isinstance(dossier.get("sources"), list)
                or len(dossier["sources"]) > MAX_SOURCE_ROWS):
            raise ValueError("dossier prive non conforme")
        seen.add(dossier["id"])
        archival = _archive_matches(dossier, history["knownFestivals"])
        exact, conflicting = _public_matches(dossier, public["festivals"])
        city_variants = _published_city_variants(dossier, public["festivals"])
        primary = _primary_proof(dossier, leads, state, today)
        # Archive homepage claims are syntactic hints, not a validated
        # primary source or proof that a festival edition exists.
        archive_date_hints = dossier.get(
            "historical_homepage_date_hints_review_only", [])
        if not isinstance(archive_date_hints, list) or len(archive_date_hints) > 3:
            raise ValueError("dates historiques privées invalides")
        from historical_future_lead_watch import _valid_private_date_hints
        accepted_archive_hints = _valid_private_date_hints(
            archive_date_hints, dossier.get("edition_year_hint"), today)
        if accepted_archive_hints is None:
            raise ValueError("indices de dates historiques altérés")
        if accepted_archive_hints and not any(
                item.get("kind") == "HISTORICAL_HOMEPAGE_YEAR_HINT"
                and item.get("publication_authorized") is False
                for item in dossier["sources"] if isinstance(item, dict)):
            raise ValueError("indice de dates historique sans source approuvée")
        uncovered_archive_dates = _uncovered_homepage_dates(
            dossier, accepted_archive_hints, public["festivals"])
        # Validate the exact pinned source and untrusted private observation
        # before admitting a review-only institutional future-date claim.
        institutional_date_hints = dossier.get(
            "institutional_future_date_hints_review_only", [])
        if not isinstance(institutional_date_hints, list) or len(institutional_date_hints) > 1:
            raise ValueError("dates institutionnelles privées invalides")
        from targeted_institutional_future_watch import validated_observations
        observations = validated_observations(state, today)
        accepted_institutional = []
        for hint in institutional_date_hints:
            if not isinstance(hint, dict):
                raise ValueError("indice institutionnel malformé")
            matching = [obs for obs in observations
                        if obs["name"] == dossier["name_hint"]
                        and obs["region"] == dossier["region_hint"]
                        and int(obs["start"][:4]) == dossier["edition_year_hint"]
                        and hint == {
                            "start_date_hint": obs["start"],
                            "end_date_hint": obs["end"],
                            "city_name_hint": obs["city"],
                            "venue_name_hint": obs["venue"],
                            "official_home": obs["official_home"],
                            "official_home_future_dates_visible": obs["primary_same_dates"],
                            "organizer_name_home_review_only": obs["organizer_name_on_home_review_only"],
                            "provider_claim": obs["provider"],
                            "institutional_source_url": obs["institutional_url"],
                            "observed_at": obs["last"],
                            "publication_authorized": False,
                            "review_only": True, "independence_verified": False,
                            "edition_dates_verified": False,
                        }
                        and any(
                            witness.get("kind") == "INSTITUTIONAL_FUTURE_DATE_HINT"
                            and witness.get("url") == obs["institutional_url"]
                            and witness.get("discovered_via") == obs["institutional_url"]
                            and witness.get("publication_authorized") is False
                            for witness in dossier["sources"]
                            if isinstance(witness, dict))]
            if len(matching) != 1:
                raise ValueError("indice institutionnel sans preuve courante approuvée")
            accepted_institutional.append(dict(hint))
        uncovered_institutional = _uncovered_homepage_dates(
            dossier, accepted_institutional, public["festivals"])
        detail_clues = _dynamic_proofs(dossier, detail)
        cancellation = any(row["possible_cancellation"] for row in detail_clues)
        event_clues = [hint for row in detail_clues
                       for hint in row.get("structured_event_clues_private", [])]
        ambiguous_history = len(archival) > 1
        if exact and (uncovered_archive_dates or uncovered_institutional):
            status = "POTENTIAL_CONFLICT_REVIEW"
        elif exact:
            status = "PUBLISHED_EDITION_MATCH_REVIEW"
        elif conflicting or city_variants or ambiguous_history or cancellation:
            status = "POTENTIAL_CONFLICT_REVIEW"
        elif primary and primary["dates_visible_in_primary"]:
            status = "PRIMARY_DATE_CLAIM_REVIEW"
        elif any(x["name_seen"] and x["edition_year_near_name"] for x in detail_clues):
            status = "REGIONAL_NAME_YEAR_REVIEW"
        elif accepted_institutional:
            status = ("INSTITUTIONAL_AND_ORGANIZER_DATE_HINT_REVIEW"
                      if any(x["official_home_future_dates_visible"]
                             for x in accepted_institutional)
                      else "INSTITUTIONAL_ONLY_FUTURE_DATE_REVIEW")
        elif accepted_archive_hints:
            status = "ARCHIVAL_VISIBLE_DATE_HINT_REVIEW"
        else:
            status = "RESEARCH_REQUIRED"
        blocks = ["editorial_approval", "organizer_identity", "venue_and_department",
                  "independent_date_confirmation", "coordinates_review",
                  "lineup_review", "ticketing_review", "duplicate_review"]
        if not primary:
            blocks.append("first_party_date_observation_missing")
        if not detail_clues and not primary:
            blocks.append("edition_detail_proof_missing")
        if accepted_institutional:
            blocks.append("institutional_syndication_not_independent_confirmation")
            blocks.append("institutional_future_dates_require_editorial_review")
            if not any(x["official_home_future_dates_visible"]
                       for x in accepted_institutional):
                blocks.append("organizer_site_not_yet_confirming_future_dates")
        if accepted_archive_hints:
            blocks.append("archival_visible_dates_require_primary_confirmation")
            if len(accepted_archive_hints) > 1:
                blocks.append("possible_multiple_same_year_editions_need_review")
        if not dossier.get("edition_year_hint"):
            blocks.append("edition_year_unknown")
        if exact:
            blocks.append("already_published_edition")
        if exact and (uncovered_archive_dates or uncovered_institutional):
            blocks.append("published_same_year_may_hide_other_edition")
        if conflicting:
            blocks.append("same_name_year_region_city_conflict")
        if city_variants:
            blocks.append("published_title_city_variant_needs_review")
        if ambiguous_history:
            blocks.append("ambiguous_historical_identity")
        if cancellation:
            blocks.append("possible_cancellation_review")
        row = {
            "id": dossier["id"], "name_hint": dossier["name_hint"],
            "edition_year_hint": dossier["edition_year_hint"],
            "region_hint": dossier["region_hint"],
            "city_hint": dossier.get("city_hint"),
            "status": status, "publication_authorized": False,
            "safe_to_publish": False, "review_only": True,
            "archive_identity_hints": archival,
            "published_exact_edition_matches": exact,
            "published_city_conflicts": conflicting,
            "published_title_city_variants_review_only": city_variants,
            "primary_observation": primary,
            "regional_detail_observations": detail_clues,
            "historical_homepage_date_hints_review_only": accepted_archive_hints,
            "historical_homepage_uncovered_dates_review_only": uncovered_archive_dates,
            "institutional_future_date_hints_review_only": accepted_institutional,
            "institutional_future_uncovered_dates_review_only": uncovered_institutional,
            "structured_date_hints_count": len(event_clues),
            "named_organizer_hints_count": sum(
                bool(h.get("organizer_name_hint")) for h in event_clues),
            "visible_start_date_hints_count": sum(
                h["start_date_visible_near_name"] for h in event_clues),
            "independence_verified": False,
            "future_edition_confirmed": False,
            "missing_checks": sorted(set(blocks)),
        }
        result.append(row)
        # A draft is prepared only for an observed future-date claim on a
        # reviewed curated primary, never merely because the archive is older.
        if (status == "PRIMARY_DATE_CLAIM_REVIEW"
                and primary and primary["start_date_hint"]
                and date.fromisoformat(primary["start_date_hint"]) > date.fromisoformat(today)):
            proposed.append({
                "id": dossier["id"], "status": "PRIVATE_EDITORIAL_DRAFT",
                "review_only": True, "publication_authorized": False,
                "safe_to_publish": False,
                "primary_source_url": primary["source_url"],
                "primary_observed_at": primary["observed_at"],
                "candidate_fields_unverified": {
                    "name_hint": dossier["name_hint"],
                    "edition_year_hint": dossier["edition_year_hint"],
                    "start_date_hint": primary["start_date_hint"],
                    "end_date_hint": primary["end_date_hint"],
                    "city": None, "department": None, "venue": None,
                    "organizer": None, "lineup": None, "ticketing": None,
                    "coordinates": None,
                },
                "missing_checks": list(row["missing_checks"]),
            })
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "publications": 0, "public_editions_count": len(public["festivals"]),
        "historic_references_count": len(history["knownFestivals"]),
        "dossiers_count": len(result),
        "historical_identity_hints_count": sum(bool(x["archive_identity_hints"]) for x in result),
        "published_duplicate_dossiers_count": sum(bool(x["published_exact_edition_matches"]) for x in result),
        "published_title_city_variant_dossiers_count": sum(
            bool(x["published_title_city_variants_review_only"]) for x in result),
        "primary_observed_dossiers_count": sum(x["primary_observation"] is not None for x in result),
        "regional_detail_observed_dossiers_count": sum(bool(x["regional_detail_observations"]) for x in result),
        "historical_homepage_date_dossiers_private": sum(
            bool(x["historical_homepage_date_hints_review_only"]) for x in result),
        "historical_homepage_visible_date_hints_private": sum(
            len(x["historical_homepage_date_hints_review_only"]) for x in result),
        "historical_homepage_uncovered_date_hints_private": sum(
            len(x["historical_homepage_uncovered_dates_review_only"])
            for x in result),
        "institutional_future_date_dossiers_private": sum(
            bool(x["institutional_future_date_hints_review_only"]) for x in result),
        "institutional_future_source_agreements_private": sum(
            any(h["official_home_future_dates_visible"]
                for h in x["institutional_future_date_hints_review_only"])
            for x in result),
        "structured_date_hints_count": sum(x["structured_date_hints_count"] for x in result),
        "organizer_name_hints_count": sum(x["named_organizer_hints_count"] for x in result),
        "visible_start_date_hints_count": sum(x["visible_start_date_hints_count"] for x in result),
        "editorial_drafts_count": len(proposed),
        "dossiers": result,
        "editorial_drafts_private": proposed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    intake = args.intake
    queue = json.loads((intake / "national-festival-discovery-review.json")
                       .read_text(encoding="utf-8"))
    detail = json.loads((intake / "national-festival-detail-review.json")
                        .read_text(encoding="utf-8"))
    state = json.loads((intake / "source-watch-state.json").read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("schema") != "grossesondes.source-watch-report.v1" or report.get("date") != today:
        raise ValueError("rapport de veille invalide")
    # Fixed first-party catalogue URLs; untrusted state supplies NO destinations.
    pages, git = get_json(PAGES), get_json(GIT)
    historic_pages, historic_git = get_json(HISTORY_PAGES), get_json(HISTORY_GIT)
    if pages != git or historic_pages != historic_git:
        raise ValueError("catalogues publics divergents : rapprochement suspendu")
    leads = load_leads(json.loads(Path(__file__).with_name(
        "curated_future_leads.json").read_text(encoding="utf-8")))
    review = build_review(queue, detail, state, leads, git, historic_git, today)
    (intake / "national-festival-editorial-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["national_reconcile_dossiers_private"] = review["dossiers_count"]
    report["national_reconcile_archive_hints_private"] = review["historical_identity_hints_count"]
    report["national_reconcile_duplicate_dossiers_private"] = review["published_duplicate_dossiers_count"]
    report["national_reconcile_primary_seen_private"] = review["primary_observed_dossiers_count"]
    report["national_reconcile_editorial_drafts_private"] = review["editorial_drafts_count"]
    report["national_reconcile_structured_date_hints_private"] = review["structured_date_hints_count"]
    report["national_reconcile_organizer_hints_private"] = review["organizer_name_hints_count"]
    report["national_reconcile_publications"] = 0
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("RECONCILIATION_FESTIVALS_PRIVEE:", json.dumps({
        "dossiers": review["dossiers_count"],
        "archive_hints": review["historical_identity_hints_count"],
        "duplicates": review["published_duplicate_dossiers_count"],
        "primary_observed": review["primary_observed_dossiers_count"],
        "drafts": review["editorial_drafts_count"],
        "structured_date_hints": review["structured_date_hints_count"],
        "organizer_hints": review["organizer_name_hints_count"],
        "published": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
