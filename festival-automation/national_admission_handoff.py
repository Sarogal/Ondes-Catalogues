"""Private-only bridge between national festival evidence and publisher proof gates.

No patch, authorisation, catalogue or publication file is ever written.
"""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from national_candidate_promotion import (
    APPROVED, SCHEMA as CANDIDATE_SCHEMA, EDITORIAL_SCHEMA, normalized,
)

SCHEMA = "grossesondes.national-publisher-handoff-private.v1"
CORE_STATUSES = {
    "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE",
    "FIRST_PARTY_EDITION_RECHECKED_LINEUP_PENDING_PRIVATE",
}
GATES = [
    "current_edition_jsonld_independent_recheck",
    "archive_parent_publisher_route_review",
    "independent_date_confirmation",
    "edition_2027_venue_confirmation",
    "venue_coordinates_confirmation",
    "editorial_signoff",
    "publication_sync_gate_not_connected",
]


def _review_only(row):
    return (isinstance(row, dict) and row.get("review_only") is True
            and row.get("safe_to_publish") is False
            and row.get("publication_authorized") is False)


def _year(value):
    try:
        return date.fromisoformat(value).year
    except (ValueError, TypeError):
        return None


def _host(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.port):
            return None
        return parsed.hostname.lower()
    except ValueError:
        return None


def _archive_parent(history, spec):
    matches = [r for r in history["knownFestivals"]
               if isinstance(r, dict)
               and normalized(r.get("name", "")) == normalized(spec["dossier_name"])
               and normalized(r.get("region", "")) == normalized(spec["region"])
               and type(r.get("lastKnownYear")) is int
               and r["lastKnownYear"] == spec["year"] - 1
               and _year(r.get("startDate")) == spec["year"] - 1
               and _year(r.get("endDate")) == spec["year"] - 1
               and _host(r.get("officialSite")) == _host(spec["dates_url"])]
    return matches[0] if len(matches) == 1 else None


def build_handoff(editorial, candidate, published, history, today):
    today_date = date.fromisoformat(today)
    if (not _review_only(editorial) or not _review_only(candidate)
            or editorial.get("schema") != EDITORIAL_SCHEMA
            or candidate.get("schema") != CANDIDATE_SCHEMA
            or editorial.get("as_of") != today or candidate.get("as_of") != today
            or candidate.get("source_review_as_of") != today
            or editorial.get("publications") != 0 or candidate.get("publications") != 0
            or published.get("schema") != 1 or history.get("schema") != 2):
        raise ValueError("Unsafe or stale publisher handoff")
    e = editorial.get("dossiers")
    c = candidate.get("dossiers")
    if (not isinstance(e, list) or not isinstance(c, list)
            or not isinstance(published.get("festivals"), list)
            or not isinstance(history.get("knownFestivals"), list)
            or len(e) > 500 or len(e) != len(c)
            or len(e) != editorial.get("dossiers_count")
            or len(c) != candidate.get("dossiers_total")):
        raise ValueError("Invalid publisher handoff count")
    by_id = {}
    for row in c:
        if (not _review_only(row) or not isinstance(row.get("id"), str)
                or row["id"] in by_id):
            raise ValueError("Unsafe or duplicate preflight row")
        by_id[row["id"]] = row
    output = []
    core_count = 0
    for row in e:
        if (not _review_only(row) or not isinstance(row.get("id"), str)
                or row["id"] not in by_id):
            raise ValueError("Unsafe or unmatched editorial dossier")
        current = by_id[row["id"]]
        if (row.get("name_hint") != current.get("name_hint")
                or row.get("edition_year_hint") != current.get("edition_year_hint")):
            raise ValueError("Editorial/preflight identity mismatch")
        result = {
            "id": row["id"],
            "name_hint": row.get("name_hint"),
            "edition_year_hint": row.get("edition_year_hint"),
            "status": "PRIMARY_EVIDENCE_PENDING",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "publisher_patch_ready": False,
            "archive_parent_slug_review_only": None,
            "edition_core_review_only": None,
            "required_checks": ["code_reviewed_primary_edition_recheck"],
        }
        if current.get("status") not in CORE_STATUSES:
            if current.get("verified_fields_private"):
                raise ValueError("Unverified dossier carries certified fields")
            output.append(result)
            continue
        spec = next((s for s in APPROVED.values()
                     if normalized(s["dossier_name"]) ==
                     normalized(row.get("name_hint", ""))
                     and row.get("edition_year_hint") == s["year"]
                     and row.get("region_hint") == s["region"]), None)
        if spec is None:
            raise ValueError("Unregistered source falsely claims verified core")
        expected = {
            "name": spec["dossier_name"] + " " + str(spec["year"]),
            "startDate": spec["start"], "endDate": spec["end"],
            "city": spec["city"], "department": spec["department"],
            "region": spec["region"], "organizer": spec["organizer"],
        }
        fields = current.get("verified_fields_private")
        if (not isinstance(fields, dict)
                or any(fields.get(k) != v for k, v in expected.items())
                or set(fields) - (set(expected) | {"lineup", "bands"})
                or _year(fields["startDate"]) != spec["year"]
                or date.fromisoformat(fields["startDate"]) <= today_date):
            raise ValueError("Forged publisher edition core")
        if ("lineup" in fields or "bands" in fields) and (
                fields.get("lineup") != list(spec["bands"])
                or fields.get("bands") != len(spec["bands"])):
            raise ValueError("Unregistered artists in private core")
        checked = current.get("checked_official_urls")
        if (not isinstance(checked, list)
                or spec["dates_url"] not in checked
                or spec["organizer_url"] not in checked):
            raise ValueError("Missing organizer and edition recheck")
        # The publication gate must independently refetch the approved URL;
        # this offline document cannot certify it or invent a patch.
        if (row.get("published_exact_edition_matches")
                or row.get("published_city_conflicts")
                or row.get("published_title_city_variants_review_only")
                or any(isinstance(x, dict)
                       and normalized(x.get("name", "")) == normalized(expected["name"])
                       and _year(x.get("startDate")) == spec["year"]
                       for x in published["festivals"])):
            result["status"] = "DUPLICATE_OR_CONFLICT_REVIEW"
            result["required_checks"] = ["duplicate_and_city_conflict_review"]
        else:
            parent = _archive_parent(history, spec)
            result.update(
                status=("ARCHIVED_PUBLISHER_PROOF_REQUIRED" if parent
                        else "NO_TRUSTED_ARCHIVE_PARENT"),
                archive_parent_slug_review_only=(
                    parent.get("slug") if parent else None),
                edition_core_review_only=dict(expected),
                required_checks=(list(GATES) if parent else
                                 ["trusted_publisher_parent_missing", *GATES]),
            )
        core_count += 1
        output.append(result)
    if (set(by_id) != {x["id"] for x in output}
            or (candidate.get("edition_core_rechecked_count") is not None
                and candidate["edition_core_rechecked_count"] != core_count)):
        raise ValueError("Missing or inconsistent handoff dossier")
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "publisher_patch_created": False, "publisher_gate_connected": False,
        "dossiers_total": len(output),
        "edition_cores_rechecked_private": core_count,
        "archive_parents_identified_private": sum(
            x["archive_parent_slug_review_only"] is not None for x in output),
        "publisher_ready_count": 0,
        "dossiers": output,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    result = build_handoff(
        read(args.intake / "national-festival-editorial-review.json"),
        read(args.intake / "national-festival-candidate-review.json"),
        read(args.catalog), read(args.history), today)
    (args.intake / "national-festival-publisher-handoff.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("PRIVATE_PUBLISHER_HANDOFF: no patch, publication or authorization")


if __name__ == "__main__":
    main()
