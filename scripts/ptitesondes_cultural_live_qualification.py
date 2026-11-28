"""Read-only live rehearsal of the production cultural qualification route."""
from collections import Counter
from datetime import date
import json
from ptitesondes_cultural_directory_discovery import scan
from ptitesondes_unlisted_source_safe_recheck import read_failure_counts
from ptitesondes_open_world_permanent_place_ban import (
    discover_ban_routes, ban_diagnostics, build_ban_draft,
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


if __name__ == "__main__":
    try:
        for page in (1, 37):
            result = probe(discover=lambda: scan(previous_page=page))
            print(json.dumps({"sample_start_page": page, **result}, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("::error::Cultural live qualification sample unavailable")
        raise SystemExit(1) from None
