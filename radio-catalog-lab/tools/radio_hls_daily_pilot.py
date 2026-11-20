#!/usr/bin/env python3
"""Non-publishing sample of new HLS-looking radio URLs from the daily discovery.

Selection is by URL shape, never a hardcoded station UUID. The existing
DNS-pinned, HTTPS-validating probe is reused; HLS variants and segments are
never followed. A completed manifest is NOT verified audio.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Callable

from radio_stream_technical_probe import (
    MAX_INPUT_SIZE, PinnedHttpTransport, ResponseSample, probe_url,
)
from radio_hls_segment_evidence import verify_one_segment, safe_segment_transport

MAX_HLS_CANDIDATES = 5


def select_hls_candidates(
    discovery: dict, *, day: dt.date, limit: int = MAX_HLS_CANDIDATES,
) -> list[tuple[str, str]]:
    if not isinstance(discovery, dict) or discovery.get("schemaVersion") != 1 or (
        discovery.get("publicationAllowed") is not False or
        not isinstance(discovery.get("candidates"), list)):
        raise ValueError("Untrusted HLS discovery input")
    if not 1 <= limit <= MAX_HLS_CANDIDATES:
        raise ValueError("Invalid HLS probe budget")
    if len(discovery["candidates"]) > 20000:
        raise ValueError("HLS candidate list too large")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in discovery["candidates"]:
        if not isinstance(row, dict):
            raise ValueError("Invalid candidate")
        raw_id = row.get("stationuuid")
        try:
            identity = str(uuid.UUID(raw_id)) if isinstance(raw_id, str) else ""
        except ValueError as error:
            raise ValueError("Invalid station UUID") from error
        if not identity or identity != raw_id or identity in seen:
            raise ValueError("Duplicate or noncanonical station UUID")
        seen.add(identity)
        if row.get("status") not in {
            "candidate_requires_qualification", "needs_stream_check",
            "needs_duplicate_review",
        }:
            raise ValueError("Unrecognized candidate state")
        if row["status"] == "needs_duplicate_review":
            continue
        source = row.get("streamUrl")
        if not isinstance(source, str) or len(source) > 2048:
            continue
        try:
            url = urllib.parse.urlsplit(source)
        except ValueError:
            continue
        if url.scheme in ("http", "https") and url.path.lower().endswith(".m3u8"):
            result.append((identity, source))
    result.sort()
    if not result:
        return []
    start = (day.toordinal() * limit) % len(result)
    return [result[(start + i) % len(result)] for i in range(min(limit, len(result)))]


def hls_preview(
    discovery: dict, request: Callable[[str], ResponseSample],
    *, day: dt.date, limit: int = MAX_HLS_CANDIDATES,
    check_one_segment: bool = False,
    segment_request: Callable[[str], ResponseSample] | None = None,
    experimental_decode_segment: bool = False,
) -> dict:
    if experimental_decode_segment and not check_one_segment:
        raise ValueError("PCM decoding requires explicit segment checking")
    if check_one_segment and segment_request is None:
        raise ValueError("Explicit segment sampler required")
    selected = select_hls_candidates(discovery, day=day, limit=limit)
    checks = []
    kinds: dict[str, int] = {}
    segment_checks = 0
    structural_evidence = 0
    pcm_evidence = 0
    segment_states: dict[str, int] = {}
    planning_reasons: dict[str, int] = {}
    safe_options: list[tuple[int, dict, str]] = []
    for uid, raw_url in selected:
        # Same pinned DNS and redirect checks as all other radio probes.
        report = probe_url(raw_url, request)
        hls = report.get("hlsEvidence") or {}
        kind = hls.get("kind", "no_manifest_observed")
        kinds[kind] = kinds.get(kind, 0) + 1
        check = {
            "stationuuid": uid,
            "verdict": report["verdict"],
            "reason": report["reason"],
            "streamSha256": report["streamSha256"],
            "hlsKind": kind,
            "publicationAllowed": False,
        }
        if kind in {"live_manifest_candidate", "master_single_variant_pending"}:
            # URLs remain ephemeral local inputs, never returned or uploaded.
            priority = 0 if kind == "live_manifest_candidate" else 1
            safe_options.append((priority, check, raw_url))
        checks.append(check)
    if check_one_segment and safe_options:
        # Prefer a media playlist already containing segment references; only
        # descend a master when there is no simpler live-media candidate.
        _, check, raw_url = sorted(safe_options, key=lambda pair: pair[0])[0]
        segment_checks = 1
        outcome = verify_one_segment(
            raw_url, request, segment_request,
            experimental_decode=experimental_decode_segment)
        check["segmentCheck"] = outcome
        state = outcome["state"]
        segment_states[state] = 1
        reason = outcome.get("planningReason", "not_evaluated")
        planning_reasons[reason] = 1
        if state == "segment_structural_evidence":
            structural_evidence = 1
        if (outcome.get("segmentDecodeEvidence") or {}).get("state") == "decoded_pcm":
            pcm_evidence = 1
    return {
        "schemaVersion": 1,
        "observationDate": day.isoformat(),
        "checkedCount": len(checks),
        "liveManifestCandidateCount": kinds.get("live_manifest_candidate", 0),
        "manifestKinds": dict(sorted(kinds.items())),
        "segmentVerificationAttemptCount": segment_checks,
        "segmentStructuralEvidenceCount": structural_evidence,
        "decodedPcmSegmentCount": pcm_evidence,
        "segmentStates": dict(sorted(segment_states.items())),
        "segmentPlanningReasons": dict(sorted(planning_reasons.items())),
        "technicalVerifiedCount": 0,
        "publicationAllowed": False,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--check-one-segment", action="store_true",
                        help="Experimental: at most one 16KiB HLS segment; NO admission")
    parser.add_argument("--experimental-decode-segment", action="store_true",
                        help="Decode PCM on an isolated FFmpeg runner after structure checks")
    args = parser.parse_args(argv)
    if args.experimental_decode_segment and not args.check_one_segment:
        parser.error("PCM decoding requires --check-one-segment")
    if not args.allow_network:
        parser.error("HLS network preview requires --allow-network")
    if args.discovery.stat().st_size > MAX_INPUT_SIZE:
        parser.error("HLS discovery input too large")
    data = json.loads(args.discovery.read_text(encoding="utf-8"))
    output = hls_preview(
        data, PinnedHttpTransport().request,
        day=dt.datetime.now(dt.timezone.utc).date(), limit=args.limit,
        check_one_segment=args.check_one_segment,
        segment_request=(safe_segment_transport().request
                         if args.check_one_segment else None),
        experimental_decode_segment=args.experimental_decode_segment,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"HLS_MANIFEST_PREVIEW_ONLY sampled={output['checkedCount']} "
          f"possible_live_manifests={output['liveManifestCandidateCount']} "
          f"types={output['manifestKinds']} "
          f"segment_attempts={output['segmentVerificationAttemptCount']} "
          f"segment_structures={output['segmentStructuralEvidenceCount']} "
          f"segment_pcm={output['decodedPcmSegmentCount']} "
          f"segment_states={output['segmentStates']} "
          f"segment_planning={output['segmentPlanningReasons']} "
          "verified=0 published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
