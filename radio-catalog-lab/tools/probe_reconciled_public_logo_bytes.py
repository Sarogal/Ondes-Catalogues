#!/usr/bin/env python3
"""Opt-in read-only SHA/decoder audit for all public-manifest logo candidates.

This is NOT a signed logo publisher. It reuses the existing bounded HTTPS,
DNS, redirect, image decoder and byte-limit checks; never stores image files.
One public URL is probed once per run regardless of radio/UUID count.
Every result requires a separate identity and visual-quality review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from audit_open_radio_artwork_inventory import public_https, probe_image


class ProbeQueueError(ValueError):
    pass


def candidate_urls(review: dict) -> dict[str, list[str]]:
    if (not isinstance(review, dict) or
            review.get("scope") != "GROSSES_ONDES_LEGACY_ARTWORK_RECONCILIATION_UNREVIEWED" or
            review.get("publication_allowed") is not False or
            review.get("signed_catalog_created") is not False or
            review.get("discovery_is_open") is not True):
        raise ProbeQueueError("Refusing unreviewed/unsigned queue without safe flags")
    result = defaultdict(set)
    all_ids = set()
    for group in ("historical_stations", "unmatched_public_manifest_ids"):
        records = review.get(group)
        if not isinstance(records, list):
            raise ProbeQueueError("Missing historical/unmatched station candidates")
        for station in records:
            if not isinstance(station, dict) or \
                    station.get("publication_allowed") is not False or \
                    station.get("visual_identity_approved") is not False:
                raise ProbeQueueError("Candidate incorrectly marked as editorially approved")
            id_ = station.get("legacy_media_id")
            if not isinstance(id_, str) or not id_ or id_ in all_ids:
                raise ProbeQueueError("Missing/duplicate station identity")
            all_ids.add(id_)
            entries = station.get("candidates")
            if not isinstance(entries, list):
                raise ProbeQueueError("Candidate evidence list missing")
            for entry in entries:
                if not isinstance(entry, dict) or \
                        entry.get("requires_byte_sha_and_visual_review") is not True or \
                        entry.get("publication_allowed") is not False:
                    raise ProbeQueueError("Candidate lacks no-publication evidence flags")
                if entry.get("evidence_source") != "live_public_manifest":
                    continue
                url = entry.get("url")
                if not isinstance(url, str) or \
                        entry.get("safe_public_https_candidate") is not public_https(url):
                    raise ProbeQueueError("Source URL safety assertion mismatch")
                result[url].add(id_)
    return {url: sorted(ids) for url, ids in sorted(result.items())}


def probe(review: dict, *, shard_index: int, shard_count: int,
          network: bool = False, image_probe=probe_image) -> dict:
    if not (type(shard_index) is int and type(shard_count) is int and
            1 <= shard_count <= 64 and 0 <= shard_index < shard_count):
        raise ProbeQueueError("Invalid scan shard")
    candidates = candidate_urls(review)
    # Hash-based sharding is stable when new sources are discovered: an
    # unrelated new URL must not move previously checked logos across shards.
    selected = [(url, ids) for url, ids in candidates.items()
                if int(hashlib.sha256(url.encode("utf-8")).hexdigest()[:8], 16)
                % shard_count == shard_index]
    if network and len(selected) > 64:
        raise ProbeQueueError("Refuse too many logo requests in one network shard")
    records = []
    for url, ids in selected:
        safe = public_https(url)
        evidence = (image_probe(url) if network and safe
                    else {"verified_bytes": False,
                          "reason": ("offline_no_network" if safe
                                     else "unsafe_public_https_candidate")})
        if not isinstance(evidence, dict) or evidence.get("approved_station_logo") is True:
            raise ProbeQueueError("A byte probe must not approve the station identity")
        records.append({
            "url": url,
            "legacy_media_ids": ids,
            "source_manifest_version": review["public_manifest_version"],
            "probe": evidence,
            "needs_station_identity_review": True,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "scope": "GROSSES_ONDES_PUBLIC_MANIFEST_LOGO_SHA_EVIDENCE_ONLY",
        "public_manifest_version": review["public_manifest_version"],
        "total_unique_manifest_urls": len(candidates),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "network_enabled": network,
        "url_attempts": len(selected) if network else 0,
        "unique_candidate_urls_in_shard": len(selected),
        "verified_image_bytes": sum(row["probe"].get("verified_bytes") is True
                                    for row in records),
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--network", action="store_true",
                        help="Opt in to bounded HTTPS probes; default is offline")
    args = parser.parse_args()
    review = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    result = probe(review, shard_index=args.shard_index,
                   shard_count=args.shard_count, network=args.network)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True,
                                      ensure_ascii=False, indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": "GO_PUBLIC_MANIFEST_SHA_EVIDENCE_ONLY",
        "manifest": result["public_manifest_version"],
        "unique_urls": result["total_unique_manifest_urls"],
        "shard_index": result["shard_index"],
        "selected": result["unique_candidate_urls_in_shard"],
        "verified_bytes": result["verified_image_bytes"],
        "publication_allowed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
