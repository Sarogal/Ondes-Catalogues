#!/usr/bin/env python3
"""Offline, fail-closed rights/identity gate for real radio-logo candidates.

Technical SHA-256 is NEVER a grant to rehost or embed a station's artwork.
The v1 ledger is intentionally BLOCK-ONLY. An actual permission grant requires
a separately reviewed future schema with documented evidence and sign-off.
No network, no contact, no send, no publication; JSON preview only.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r"^[0-9a-f]{64}$")
RIGHTS = {
    "PROHIBITS_NEW_THIRD_PARTY_APPS",
    "WRITTEN_PERMISSION_REQUIRED",
    "PERMISSION_NOT_DOCUMENTED",
}
SHA_STATES = {
    "TWO_MATCHING_REMOTE_SHA_NOT_REHOSTED",
    "NO_RELIABLE_BYTES",
}
GO_ID = re.compile(r"^go-station-\d{6,}$")


def _urls_by_source(rows: list, *, label: str) -> dict:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"Missing {label} entries")
    mapping = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Non-object {label} entry")
        url = row.get("source_url")
        if not isinstance(url, str) or not url.startswith("https://") or url in mapping:
            raise ValueError(f"Invalid or duplicate {label} source")
        mapping[url] = row
    return mapping


def audit_logo_rights(pilot: dict, network: dict, rights: dict) -> dict:
    if not all(isinstance(x, dict) for x in (pilot, network, rights)):
        raise ValueError("Invalid JSON input")
    if (pilot.get("schema_version") != 1 or network.get("schema_version") != 1
            or rights.get("schema_version") != 1
            or rights.get("ledger_kind") != "THIRD_PARTY_RADIO_LOGO_RIGHTS_REGISTER"):
        raise ValueError("Unrecognized input schema")
    if (rights.get("approved_logos") != 0 or rights.get("permission_replies_received") != 0
            or rights.get("emails_sent") != 0 or rights.get("catalog_publication_authorized") is not False):
        raise ValueError("v1 ledger cannot assert a grant, contact or publication")
    if (network.get("catalog_signed") is not False or network.get("production_modified") is not False
            or network.get("approved_logo_count") != 0):
        raise ValueError("Network observation is not a read-only unsigned proof")
    selected = _urls_by_source(pilot.get("entries"), label="pilot")
    observed = _urls_by_source(network.get("observations"), label="network")
    reviewed = _urls_by_source(rights.get("records"), label="rights")
    if len(selected) > 8 or set(selected) != set(observed) or set(selected) != set(reviewed):
        raise ValueError("Pilot/network/rights URL sets are not identical")
    status_counts = Counter()
    stable_sha = 0
    go_owners = set()
    blocked_go_ids = set()
    review_rows = []
    for url in sorted(selected):
        p = selected[url]
        o = observed[url]
        r = reviewed[url]
        ids = p.get("go_station_ids")
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(x, str) or not GO_ID.fullmatch(x) for x in ids)
                or len(ids) != len(set(ids))
                or sorted(ids) != sorted(o.get("historical_go_station_ids", []))
                or sorted(ids) != sorted(r.get("go_station_ids", []))):
            raise ValueError("GO identity mismatch in rights ledger")
        for go_id in ids:
            if go_id in go_owners:
                raise ValueError("GO ID assigned to multiple pilot image sources")
            go_owners.add(go_id)
            blocked_go_ids.add(go_id)
        state = r.get("rights_state")
        if state not in RIGHTS:
            raise ValueError("Invalid or unapproved rights-state escalation")
        if (r.get("may_publish_immutable_logo") is not False
                or r.get("catalog_admission_authorized") is not False
                or r.get("permission_evidence_id") is not None
                or r.get("contact_status") != "NOT_CONTACTED"
                or r.get("station_identity_review") != "PENDING"
                or r.get("visual_fit_review") != "PENDING"):
            raise ValueError("Cannot claim editorial acceptance, permission, or outreach")
        evidence_urls = r.get("rights_evidence_urls")
        if not isinstance(evidence_urls, list):
            raise ValueError("Missing rights evidence links")
        if state != "PERMISSION_NOT_DOCUMENTED" and not evidence_urls:
            raise ValueError("Explicit rights restriction requires an official source")
        for href in evidence_urls:
            if (not isinstance(href, str) or urlsplit(href).scheme != "https"
                    or not urlsplit(href).hostname or urlsplit(href).username
                    or urlsplit(href).password):
                raise ValueError("Invalid rights source link")
        if (state == "PROHIBITS_NEW_THIRD_PARTY_APPS"
                and r.get("stream_terms_review") != "URGENT_SEPARATE_REVIEW"):
            raise ValueError("Third-party application prohibition requires stream-policy review")
        if r.get("stream_terms_review") not in ("URGENT_SEPARATE_REVIEW", "SEPARATE_REVIEW"):
            raise ValueError("Stream-policy review missing")
        status_counts[state] += 1

        two_sha = o.get("sha256_stable_across_two_requests") is True
        if two_sha:
            first = o.get("first_attempt")
            second = o.get("second_attempt")
            digest = first.get("sha256") if isinstance(first, dict) else None
            if (not isinstance(digest, str) or not SHA.fullmatch(digest)
                    or not isinstance(second, dict) or digest != second.get("sha256")
                    or first.get("byte_size") != second.get("byte_size")
                    or first.get("mime_type") != second.get("mime_type")
                    or first.get("width") != second.get("width")
                    or first.get("height") != second.get("height")
                    or r.get("source_sha256_observed_only") != digest
                    or r.get("artifact_sha_technical_status") != "TWO_MATCHING_REMOTE_SHA_NOT_REHOSTED"):
                raise ValueError("Technical evidence is inconsistent with two observed SHA hashes")
            stable_sha += 1
        else:
            if (r.get("source_sha256_observed_only") is not None
                    or r.get("artifact_sha_technical_status") != "NO_RELIABLE_BYTES"):
                raise ValueError("Unavailable remote image must not have an accepted SHA")
        if r.get("artifact_sha_technical_status") not in SHA_STATES:
            raise ValueError("Invalid observed SHA state")
        review_rows.append({
            "source_url": url,
            "affected_go_station_ids": sorted(ids),
            "rights_state": state,
            "technical_sha_repeated": two_sha,
            "publication_status": "BLOCKED_NEEDS_RIGHTS_AND_IDENTITY_REVIEW",
            "rehosting_allowed": False,
        })
    if stable_sha != network.get("matching_sha256_across_two_attempts"):
        raise ValueError("Network proof summary count inconsistent")

    return {
        "status": "STRICT_V1_RIGHTS_GATE_BLOCKS_ALL_PUBLICATION",
        "reviewed_source_urls": len(review_rows),
        "historical_go_station_ids_affected": len(blocked_go_ids),
        "repeated_remote_sha_sources": stable_sha,
        "rights_status_counts": dict(sorted(status_counts.items())),
        "rights_authorized_for_rehosting": 0,
        "ready_to_sign_catalog": False,
        "stream_terms_requiring_separate_review": sum(
            r["stream_terms_review"] == "URGENT_SEPARATE_REVIEW"
            for r in reviewed.values()
        ),
        "contact_actions_taken": 0,
        "site_or_app_modified": False,
        "entries": review_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--rights", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out is not None and args.out.exists():
        parser.error("Refusing to overwrite an existing report")
    result = audit_logo_rights(
        json.loads(args.pilot.read_text(encoding="utf-8")),
        json.loads(args.network.read_text(encoding="utf-8")),
        json.loads(args.rights.read_text(encoding="utf-8")),
    )
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "entries"},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
