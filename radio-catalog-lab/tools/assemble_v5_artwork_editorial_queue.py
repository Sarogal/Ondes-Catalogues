#!/usr/bin/env python3
"""Assemble v5 logo byte evidence into an EDITORIAL queue, never a publisher.

Inputs: historical UUID reconciliation, every SHA probe shard, optional existing
TEST-only visually reviewed sidecar. No network, signing, image writing, or
modification to the radio catalog. New UUIDs and providers remain discoverable.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r"^[0-9a-f]{64}$")
MIME = {"image/png", "image/jpeg", "image/webp"}
RECON_SCOPE = "GROSSES_ONDES_LEGACY_ARTWORK_RECONCILIATION_UNREVIEWED"
PROBE_SCOPE = "GROSSES_ONDES_PUBLIC_MANIFEST_LOGO_SHA_EVIDENCE_ONLY"


class ReviewQueueError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewQueueError(message)


def build_queue(reconciliation: dict, shards: list[dict],
                pilot: dict | None = None) -> dict:
    _require(reconciliation.get("scope") == RECON_SCOPE
             and reconciliation.get("publication_allowed") is False
             and reconciliation.get("signed_catalog_created") is False
             and reconciliation.get("discovery_is_open") is True,
             "Reconciliation must be unsigned and open-discovery")
    rows = reconciliation.get("historical_stations")
    unmatched = reconciliation.get("unmatched_public_manifest_ids")
    _require(isinstance(rows, list) and isinstance(unmatched, list),
             "Missing historical or unmatched UUID records")

    url_ids = defaultdict(set)
    historical = set()
    historical_associations = []
    total_associations = 0
    for group, is_historical in ((rows, True), (unmatched, False)):
        for station in group:
            sid = station.get("legacy_media_id")
            _require(isinstance(sid, str) and sid not in historical,
                     "Missing/duplicate UUID")
            historical.add(sid)
            _require(station.get("publication_allowed") is False
                     and station.get("visual_identity_approved") is False,
                     "Reconciliation row already marked approved")
            candidates = [c for c in station.get("candidates", [])
                          if c.get("evidence_source") == "live_public_manifest"]
            _require(len(candidates) <= 1, "Duplicate v5 association on UUID")
            if not candidates:
                continue
            entry = candidates[0]
            _require(entry.get("publication_allowed") is False
                     and entry.get("requires_byte_sha_and_visual_review") is True,
                     "Manifest association marked publishable")
            url = entry.get("url")
            _require(isinstance(url, str) and urlsplit(url).scheme == "https",
                     "Unexpected/non-HTTPS logo candidate URL")
            url_ids[url].add(sid)
            total_associations += 1
            if is_historical:
                historical_associations.append((station, entry))
    _require(total_associations >= len(url_ids), "Invalid v5 associations")

    observed = {}
    shard_ids = set()
    _require(bool(shards), "No probe reports supplied")
    expected_count = shards[0].get("shard_count")
    _require(type(expected_count) is int and expected_count > 0,
             "Invalid shard count")
    for shard in shards:
        index = shard.get("shard_index")
        _require(shard.get("scope") == PROBE_SCOPE
                 and shard.get("publication_allowed") is False
                 and shard.get("signed_catalog_created") is False
                 and shard.get("public_manifest_version") ==
                 reconciliation.get("public_manifest_version")
                 and shard.get("shard_count") == expected_count
                 and type(index) is int and index not in shard_ids
                 and 0 <= index < expected_count,
                 "Invalid/duplicate probe shard")
        shard_ids.add(index)
        _require(shard.get("total_unique_manifest_urls") == len(url_ids),
                 "Probe and reconciliation disagree on URL total")
        reports = shard.get("records")
        _require(isinstance(reports, list)
                 and shard.get("unique_candidate_urls_in_shard") == len(reports),
                 "Missing or incomplete shard records")
        for record in reports:
            url = record.get("url")
            _require(isinstance(url, str) and url not in observed
                     and url in url_ids
                     and record.get("publication_allowed") is False
                     and record.get("needs_station_identity_review") is True
                     and record.get("source_manifest_version") ==
                     reconciliation.get("public_manifest_version")
                     and set(record.get("legacy_media_ids", [])) == url_ids[url],
                     "Probe URL, UUIDs, or approval flags mismatch")
            evidence = record.get("probe")
            _require(isinstance(evidence, dict)
                     and evidence.get("approved_station_logo") is not True,
                     "Byte probe must not assert editorial approval")
            if evidence.get("verified_bytes") is True:
                _require(isinstance(evidence.get("sha256"), str)
                         and SHA.fullmatch(evidence["sha256"])
                         and evidence.get("mime_type") in MIME
                         and type(evidence.get("byte_size")) is int
                         and evidence["byte_size"] > 0
                         and type(evidence.get("width")) is int
                         and evidence["width"] > 0
                         and type(evidence.get("height")) is int
                         and evidence["height"] > 0,
                         "Verified byte evidence is malformed")
            observed[url] = evidence
    _require(shard_ids == set(range(expected_count))
             and set(observed) == set(url_ids),
             "Incomplete sharded evidence: fail closed")

    pilot_sha = {}
    if pilot is not None:
        _require(pilot.get("scope") == "TEST_ONLY"
                 and pilot.get("production_publication_allowed") is False
                 and pilot.get("catalog_id") == "grosses-ondes-artwork",
                 "Pilot sidecar is not TEST-only")
        for asset in pilot.get("assets", []):
            sid = asset.get("legacy_media_id")
            logo = asset.get("logo", {})
            digest = logo.get("sha256")
            _require(sid in historical and sid not in pilot_sha
                     and isinstance(digest, str) and SHA.fullmatch(digest)
                     and asset.get("replace_existing_logo") is False,
                     "Invalid pilot UUID/SHA or replacement permission")
            pilot_sha[sid] = digest

    review = []
    for station, candidate in historical_associations:
        sid = station["legacy_media_id"]
        url = candidate["url"]
        evidence = observed[url]
        meta = candidate.get("metadata") or {}
        flags = []
        if evidence.get("verified_bytes") is not True:
            flags.append("BYTE_PROBE_UNVERIFIED")
        else:
            if min(evidence["width"], evidence["height"]) < 192:
                flags.append("ACTUAL_IMAGE_UNDER_192PX")
            if (type(meta.get("reported_width")) is int
                and type(meta.get("reported_height")) is int
                and min(meta["reported_width"], meta["reported_height"]) < 192):
                flags.append("MANIFEST_IMAGE_UNDER_192PX")
        if len(url_ids[url]) > 1:
            flags.append("SHARED_IMAGE_UUIDS_NEVER_MERGE")
        path = urlsplit(url).path.lower()
        if re.search(r"(favicon|apple-touch-icon|android-chrome|og_image|header-logo|logo-blank)", path):
            flags.append("POSSIBLE_GENERIC_PLATFORM_OR_SITE_IMAGE")
        # Cross-brand warning, NOT a hardcoded radio acceptance list.
        # A relay could legitimately use an upstream station's artwork.
        if "drgnu" in station.get("station_name", "").lower() and "bob_" in path:
            flags.append("DRGNU_SOURCE_HAS_RADIO_BOB_BRANDING_REVIEW")
        if sid in pilot_sha:
            status = ("PREVIOUS_TEST_VISUAL_SHA_MATCH"
                      if evidence.get("sha256") == pilot_sha[sid]
                      else "PILOT_SHA_MISMATCH_HOLD")
        else:
            status = "IDENTITY_VISUAL_REVIEW_REQUIRED"
        review.append({
            "legacy_media_id": sid,
            "station_name": station.get("station_name", ""),
            "source_logo_initially_missing":
                "bootstrap_logo_missing" in station.get("review_flags", []),
            "source_url": url,
            "source_host": urlsplit(url).netloc,
            "probe_verified": evidence.get("verified_bytes") is True,
            "sha256": evidence.get("sha256"),
            "byte_size": evidence.get("byte_size"),
            "width": evidence.get("width"),
            "height": evidence.get("height"),
            "mime_type": evidence.get("mime_type"),
            "probe_failure": (None if evidence.get("verified_bytes") is True
                              else evidence.get("reason")),
            "editorial_review_status": status,
            "review_flags": flags,
            "publication_allowed": False,
            "replace_existing_logo": False,
        })
    review.sort(key=lambda r: (r["station_name"].casefold(), r["legacy_media_id"]))
    priority = [r for r in review if r["source_logo_initially_missing"]
                and r["probe_verified"]]
    return {
        "scope": "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "schema_version": 1,
        "source_manifest_version": reconciliation["public_manifest_version"],
        "publication_allowed": False,
        "signed_catalog_created": False,
        "discovery_is_open": True,
        "summary": {
            "historical_count": len(rows),
            "historical_manifest_associations": len(historical_associations),
            "unique_urls_checked": len(observed),
            "urls_with_verified_bytes": sum(
                e.get("verified_bytes") is True for e in observed.values()),
            "historical_uuid_with_verified_bytes": sum(
                r["probe_verified"] for r in review),
            "historical_no_bootstrap_with_verified_bytes": len(priority),
            "priority_previously_reviewed_test_sha_match": sum(
                r["editorial_review_status"] == "PREVIOUS_TEST_VISUAL_SHA_MATCH"
                for r in priority),
            "historical_declared_low_resolution": sum(
                "public_manifest_image_needs_resolution_review"
                in s.get("review_flags", []) for s in rows),
            "url_failures": sum(
                e.get("verified_bytes") is not True for e in observed.values()),
        },
        "priority_no_initial_logo": priority,
        "historical_associations": review,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--shard", type=Path, nargs="+", required=True)
    parser.add_argument("--pilot-sidecar", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--priority-csv", type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result = build_queue(read(args.reconciliation),
                         [read(p) for p in args.shard],
                         read(args.pilot_sidecar) if args.pilot_sidecar else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                      sort_keys=True) + "\n", encoding="utf-8")
    if args.priority_csv:
        args.priority_csv.parent.mkdir(parents=True, exist_ok=True)
        keys = ["station_name", "legacy_media_id", "editorial_review_status",
                "source_host", "width", "height", "sha256", "source_url",
                "review_flags", "publication_allowed"]
        with args.priority_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, delimiter=";")
            w.writeheader()
            for item in result["priority_no_initial_logo"]:
                row = {key: item.get(key) for key in keys}
                row["review_flags"] = ";".join(item["review_flags"])
                w.writerow(row)
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
