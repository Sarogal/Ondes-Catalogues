"""Private, offline audit of the ACTUAL generic national Festival -> Publisher routes.

The older national_admission_handoff only diagnoses a named legacy source.
It is not the gateway for the separately connected, independently reverified
generic directory and institutional proof modes. This report correlates the
national discovery queue, signed public catalog and the cumulative PRIVATE
patch without approving either the sources or any publication.

All route validation is structural. Only the separate cloud Publisher may
independently fetch and authorize a new edition.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from national_generic_primary_domain_preflight import _edition_name
from source_qualification import normalized

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from grossesondes_generic_directory_edition import (
    PROOF_MODE as DIRECTORY_MODE,
    validate_private_proposal as verify_directory_structure,
)
from grossesondes_institutional_linked_edition import (
    PROOF_MODE as INSTITUTION_LINKED_MODE,
    validate_private_proposal as verify_institution_linked_structure,
)
from grossesondes_institutional_edition import (
    PROOF_MODE as INSTITUTION_MODE,
    validate_private_proposal as verify_institution_structure,
)

SCHEMA = "grossesondes.national-generic-publisher-funnel-private.v1"
QUEUE_SCHEMA = "grossesondes.national-festival-discovery-private.v1"
PATCH_SCHEMA = "grossesondes.patch.v1"
STRUCTURAL_CONTRACTS = {
    DIRECTORY_MODE: verify_directory_structure,
    INSTITUTION_LINKED_MODE: verify_institution_linked_structure,
    INSTITUTION_MODE: verify_institution_structure,
}
MAX_DOSSIERS = 500
MAX_ADDITIONS = 100


def _year(value):
    try:
        return date.fromisoformat(value).year
    except (TypeError, ValueError):
        return None


def _identity(name, year):
    if (not isinstance(name, str) or not isinstance(year, int)
            or isinstance(year, bool)):
        return None
    return normalized(name), year


def build_report(discovery, patch, published, today):
    """Compare real private proposals; never trust a patch as source authority."""
    date.fromisoformat(today)
    if (not isinstance(discovery, dict)
            or discovery.get("schema") != QUEUE_SCHEMA
            or discovery.get("as_of") != today
            or discovery.get("review_only") is not True
            or discovery.get("publication_authorized") is not False
            or discovery.get("safe_to_publish") is not False
            or not isinstance(discovery.get("dossiers"), list)
            or len(discovery["dossiers"]) > MAX_DOSSIERS
            or not isinstance(patch, dict)
            or patch.get("schema") != PATCH_SCHEMA
            or patch.get("generated_at") != today
            or patch.get("safe_to_publish") is not False
            or not isinstance(patch.get("additions"), list)
            or len(patch["additions"]) > MAX_ADDITIONS
            or not isinstance(published, dict)
            or published.get("schema") != 1
            or not isinstance(published.get("festivals"), list)):
        raise ValueError("Unsafe, stale or inconsistent Festival funnel input")

    signed = set()
    for row in published["festivals"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed signed festival")
        key = _identity(row.get("name"), _year(row.get("startDate")))
        if key is not None:
            signed.add(key)

    # These are *untrusted private structures*, not certified source proofs.
    # Each contract may rederive only its own independently reviewed origin.
    by_key = {}
    structurally_valid = 0
    for row in patch["additions"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed private addition")
        mode = row.get("proofMode")
        validator = STRUCTURAL_CONTRACTS.get(mode)
        if validator is None:
            continue
        if validator(row, today) is None:
            continue
        key = _identity(row.get("name"), _year(row.get("startDate")))
        if key is None:
            continue
        structurally_valid += 1
        by_key.setdefault(key, []).append({
            "slug": row["slug"], "proof_mode": mode,
        })

    result = []
    used = set()
    seen_ids = set()
    for dossier in discovery["dossiers"]:
        if (not isinstance(dossier, dict)
                or not isinstance(dossier.get("id"), str)
                or dossier["id"] in seen_ids
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False):
            raise ValueError("Unsafe national dossier or duplicate identity")
        seen_ids.add(dossier["id"])
        title = _edition_name(
            dossier.get("name_hint"), dossier.get("edition_year_hint"))
        year = dossier.get("edition_year_hint")
        key = _identity(title, year)
        proposals = by_key.get(key, []) if key is not None else []
        row = {
            "dossier_id": dossier["id"],
            "name_hint": dossier.get("name_hint"),
            "edition_year_hint": year,
            "status": "NO_GENERIC_PUBLISHER_PROPOSAL",
            "candidate_proof_modes": [],
            "private_contracts_valid": 0,
            "independent_publisher_recheck_completed": False,
            "publication_authorized": False,
            "safe_to_publish": False,
        }
        if key is not None and key in signed:
            row["status"] = "EXACT_EDITION_ALREADY_SIGNED"
        elif len(proposals) > 1:
            row["status"] = "AMBIGUOUS_PRIVATE_GENERIC_PROPOSALS"
            row["private_contracts_valid"] = len(proposals)
            row["candidate_proof_modes"] = sorted(
                {p["proof_mode"] for p in proposals})
        elif len(proposals) == 1:
            row["status"] = "GENERIC_PUBLISHER_RECHECK_PENDING"
            row["private_contracts_valid"] = 1
            row["candidate_proof_modes"] = [proposals[0]["proof_mode"]]
            used.add(key)
        result.append(row)

    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "publisher_recheck_is_independent": True,
        "publisher_recheck_executed_by_this_report": False,
        "legacy_named_entity_registry_required": False,
        "dossiers_total": len(result),
        "already_signed_count": sum(
            r["status"] == "EXACT_EDITION_ALREADY_SIGNED" for r in result),
        "generic_publisher_recheck_pending_count": sum(
            r["status"] == "GENERIC_PUBLISHER_RECHECK_PENDING" for r in result),
        "ambiguous_generic_proposals_count": sum(
            r["status"] == "AMBIGUOUS_PRIVATE_GENERIC_PROPOSALS"
            for r in result),
        "still_without_generic_proposal_count": sum(
            r["status"] == "NO_GENERIC_PUBLISHER_PROPOSAL" for r in result),
        "structurally_valid_private_generic_additions": structurally_valid,
        "valid_generic_additions_not_linked_to_unpublished_national_dossier":
            structurally_valid - sum(len(by_key[k]) for k in used),
        "dossiers": result,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    folder = args.intake
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    report = build_report(
        read(folder / "national-festival-discovery-review.json"),
        read(folder / ("patch-" + today + ".json")),
        read(args.catalog),
        today,
    )
    (folder / "national-festival-generic-publisher-funnel.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Generic publisher funnel: national=" +
          str(report["dossiers_total"]) + ", signed=" +
          str(report["already_signed_count"]) + ", awaiting_reproof=" +
          str(report["generic_publisher_recheck_pending_count"]) +
          ", PUBLICATIONS=0")


if __name__ == "__main__":
    main()
