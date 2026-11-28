"""Read-only live rehearsal of the production cultural qualification route."""
from collections import Counter
from datetime import date
import json
from ptitesondes_cultural_directory_discovery import scan
from ptitesondes_unlisted_source_safe_recheck import read_failure_counts
from ptitesondes_open_world_permanent_place_ban import (
    discover_ban_routes, ban_diagnostics, build_ban_draft,
    fetch_communes_by_name, unique_commune_code,
)


def probe(*, discover=scan, qualify=discover_ban_routes,
          build=build_ban_draft, today=None):
    today = today or date.today()
    found = discover()
    leads = found["records"]
    before = ban_diagnostics()
    read_before = read_failure_counts()
    counts = Counter()
    for row in leads[:8]:
        counts["attempted"] += 1
        try:
            proof = qualify(row)
            if proof is None:
                counts["not_qualified"] += 1
                continue
            counts["proof_found"] += 1
            draft = build(proof, today)
            counts["valid_draft" if draft is not None else "draft_invalid"] += 1
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError):
            counts["candidate_unavailable"] += 1
    after = ban_diagnostics()
    read_after = read_failure_counts()
    return {"discovered": len(leads), "rows_examined": found["rows_examined"],
            "counts": dict(counts), "diagnostics": {
                k: v - before.get(k, 0) for k, v in after.items()
                if v > before.get(k, 0)},
            "read_failures": {k: v-read_before.get(k, 0) for k, v in read_after.items()
                              if v > read_before.get(k, 0)},
            "public_writes": 0, "publication_ready": False}


def probe_administration(leads, *, commune_fetch=fetch_communes_by_name,
                         directory_fetch=None):
    """Independently exercise the Geo API -> DILA path without Culture codes.

    Only names are used; never publish or consume a centre point.
    """
    from ptitesondes_dila_municipal_domains import fetch_dila, municipal_site_hosts
    from ptitesondes_family_national_source_preflight import norm_text
    if directory_fetch is None:
        directory_fetch = lambda city, code: fetch_dila(city, insee=code)
    counts, seen = Counter(), set()
    for row in leads[:32]:
        city = row.get("city")
        if not isinstance(city, str) or not norm_text(city) or norm_text(city) in seen:
            continue
        seen.add(norm_text(city))
        counts["attempted"] += 1
        try:
            code = unique_commune_code(city, commune_fetch(city))
            if code is None:
                counts["commune_not_unique"] += 1
            else:
                counts["unique_commune_code"] += 1
                directory = directory_fetch(city, code)
                hosts = municipal_site_hosts(city, directory, expected_insee=code)
                if hosts and hosts == municipal_site_hosts(city, directory):
                    counts["dila_authority_found"] += 1
                else:
                    counts["dila_authority_unmatched"] += 1
        except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            counts["source_unavailable"] += 1
        if counts["attempted"] >= 4:
            break
    return {"counts": dict(counts), "public_writes": 0, "publication_ready": False}


if __name__ == "__main__":
    try:
        for page in (1, 37):
            found = scan(previous_page=page)
            result = probe(discover=lambda: found)
            print(json.dumps({"sample_start_page": page, **result}, sort_keys=True))
            result = probe_administration(found["records"])
            print(json.dumps({"administration_sample_start_page": page, **result}, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("::error::Cultural live qualification sample unavailable")
        raise SystemExit(1) from None
