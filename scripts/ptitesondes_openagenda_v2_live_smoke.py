#!/usr/bin/env python3
"""Manual, read-only OpenAgenda v2 vs ODS diagnostic.

Input: a small, independently curated cases file kept OUTSIDE the repository.
This is not an organizer validation, a publisher, or a production workflow.
No candidate details, URLs, title, UID, exception string, key or event payload
may appear in output. Only fixed counters. No writes except optional stdout.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

from ptitesondes_openagenda_v2_direct_evidence import (
    read_direct_v2, review_direct_v2,
)
from ptitesondes_openagenda_v2_preintegration import group_multi_day

ODS_ENDPOINT = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/"
    "datasets/evenements-publics-openagenda/records"
)
MAX_ODS_BYTES = 120_000
MAX_INPUT_BYTES = 100_000
MAX_CASES = 12
UID = re.compile(r"[1-9][0-9]{0,11}\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def ods_exact_uid_state(uid, opener=None):
    """Only an unambiguous, successful UID lookup can certify absence.

    Unavailability, malformed totals, redirected responses and duplicate
    matches are NOT treated as absence. Never fuzzy-search titles here.
    """
    if not isinstance(uid, str) or UID.fullmatch(uid) is None:
        return "unknown"
    url = ODS_ENDPOINT + "?" + urlencode({
        "limit": 2, "select": "uid", "where": "uid='" + uid + "'",
    })
    fetch = opener or build_opener(_NoRedirect()).open
    try:
        with fetch(Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "PtitesOndesOAV2ReadOnlySmoke/1.0",
        }), timeout=18) as response:
            if response.status != 200 or response.geturl() != url:
                return "unknown"
            raw = response.read(MAX_ODS_BYTES + 1)
        if len(raw) > MAX_ODS_BYTES:
            return "unknown"
        data = json.loads(raw)
        if not isinstance(data, dict):
            return "unknown"
        rows = data.get("results")
        count = data.get("total_count")
        if (not isinstance(rows, list) or type(count) is not int
                or count < 0 or count > 1000000):
            return "unknown"
        if count == 0 and len(rows) == 0:
            return "uid_absent"
        if count == 1 and len(rows) == 1 and isinstance(rows[0], dict):
            return "uid_present" if str(rows[0].get("uid")) == uid else "conflicting"
        return "conflicting"
    except (OSError, ValueError, TypeError, UnicodeDecodeError, TimeoutError):
        return "unknown"


def _valid_cases(cases):
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("invalid_case_batch")
    for c in cases:
        if (not isinstance(c, dict)
                or set(c) != {"lead", "reviewed_agenda", "registered_venue"}
                or not isinstance(c["lead"], dict)
                or not isinstance(c["reviewed_agenda"], dict)
                or not isinstance(c["registered_venue"], dict)
                or not isinstance(c["lead"].get("external_id"), str)
                or UID.fullmatch(c["lead"]["external_id"]) is None
                or str(c["reviewed_agenda"].get("agenda_uid")) == "None"):
            raise ValueError("invalid_case_batch")


def diagnostic(cases, public_key, ods_lookup=ods_exact_uid_state,
               direct_lookup=read_direct_v2, today=None):
    """Run a small readonly batch; only return hard-coded redacted counters."""
    _valid_cases(cases)
    if today is None:
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
    result = Counter()
    for case in cases:
        lead = case["lead"]
        agenda = case["reviewed_agenda"]
        venue = case["registered_venue"]
        uid = lead["external_id"]
        # Neither UID nor URL may appear in a returned report.
        try:
            state = ods_lookup(uid)
            if state not in ("uid_absent", "uid_present", "conflicting", "unknown"):
                state = "unknown"
        except Exception:
            state = "unknown"
        result["ods_" + state] += 1
        try:
            event = direct_lookup(agenda["agenda_uid"], uid, public_key)
            proof = review_direct_v2(lead, event, agenda, venue, today)
            if proof.get("source_evidence_structurally_valid") is True:
                result["direct_structural_evidence"] += 1
                grouping = group_multi_day(event)
                if grouping.get("kind") == "one_day_explicit_slots":
                    result["single_day_structure"] += 1
                elif grouping.get("kind") == "multi_day_unresolved":
                    result["multi_day_hold"] += 1
                else:
                    result["other_grouping_hold"] += 1
            else:
                result["direct_structural_hold"] += 1
        except Exception:
            # Never stringify exceptions: network errors can contain request
            # headers or private input identities.
            result["direct_unavailable_or_invalid"] += 1
    return {
        "schema": "ptitesondes.oa2.live_read_smoke.v1",
        "mode": "manual_read_only_anonymized_no_admission",
        "checked": len(cases),
        "counts": dict(sorted(result.items())),
        "publisher_connected": False,
        "approval_granted": False, "public_writes": 0,
        "source_registry_ownership_attested": False,
        "organizer_independently_attested": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-file", required=True, type=Path)
    args = parser.parse_args()
    # The case file must be materialized in an ephemeral trusted environment,
    # never committed to a public or private git branch.
    file_size = args.cases_file.stat().st_size
    if not 0 < file_size <= MAX_INPUT_BYTES:
        raise SystemExit("invalid_case_batch")
    try:
        cases = json.loads(args.cases_file.read_text(encoding="utf-8"))
        _valid_cases(cases)
    except (ValueError, UnicodeDecodeError):
        raise SystemExit("invalid_case_batch") from None
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    if not isinstance(key, str) or not key.startswith("oa_pk_"):
        raise SystemExit("public_read_key_unavailable")
    print(json.dumps(diagnostic(cases, key), sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    main()
