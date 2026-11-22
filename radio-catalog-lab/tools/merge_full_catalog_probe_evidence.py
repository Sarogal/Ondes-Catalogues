#!/usr/bin/env python3
"""Merge 9 signed-TEST staging *probe reports*, never publish a catalog.

Every result must match the exact station ID, stream ID and URL at the
corresponding stable index of the 358-stream candidate. A failed probe never
disables, deletes or changes a stream. A successful FFmpeg decode can upgrade
only the matched stream's state to verified in a NEW unsigned evidence copy.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
from collections import Counter


def merge(catalog: dict, reports: list[dict]) -> tuple[dict, dict]:
    if catalog.get("release_sequence") != 5:
        raise ValueError("unrecognized staging generation")
    rows = copy.deepcopy(catalog["stations"])
    all_streams = [(st, stream) for st in rows for stream in st["streams"]]
    if len(all_streams) != 358:
        raise ValueError("expected full historical inventory of 358 stream entries")
    refs = set()
    outcomes = {}
    errors = Counter()
    for report in reports:
        if report.get("source_release_sequence") != 5 or report.get("publication_authorized") is not False:
            raise ValueError("untrusted probe report scope")
        if report.get("requested_streams") != 358:
            raise ValueError("a probe ran against a different radio catalog")
        offset = report.get("first_stream_index")
        entries = report.get("rows")
        if type(offset) is not int or not isinstance(entries, list) or not entries:
            raise ValueError("missing sequence offset or evidence rows")
        if offset < 0 or offset + len(entries) > 358 or report.get("probed_streams") != len(entries):
            raise ValueError("invalid probe boundaries")
        for index, evidence in enumerate(entries, offset):
            if index in refs:
                raise ValueError("duplicate stream evidence")
            refs.add(index)
            station, stream = all_streams[index]
            if (evidence.get("go_station_id") != station["go_station_id"] or
                evidence.get("stream_id") != stream["stream_id"] or
                evidence.get("url") != stream["url"]):
                raise ValueError("probe record doesn't match original signed-migration stream")
            if evidence.get("verified") is True:
                if evidence.get("result") != "audio_decoded":
                    raise ValueError("false-positive decoder verification")
                try:
                    datetime.fromisoformat(evidence["checked_at"].replace("Z", "+00:00"))
                except (ValueError, TypeError, KeyError, AttributeError) as err:
                    raise ValueError("unparseable proof timestamp") from err
                stream["state"] = "verified"
                stream["last_checked_at"] = evidence["checked_at"]
            elif evidence.get("verified") is not False:
                raise ValueError("missing explicit failed/verified decision")
            errors[str(evidence.get("result"))] += 1
            outcomes[(station["go_station_id"], stream["stream_id"])] = evidence
    if len(refs) != 358 or refs != set(range(358)):
        raise ValueError("all 358 unique stream indices must be probed exactly once")
    result = copy.deepcopy(catalog)
    result["stations"] = rows
    original = {s["go_station_id"]: s for s in catalog["stations"]}
    lacking = []
    for station in rows:
        if station["status"]["state"] != "active":
            continue
        if not any(s["state"] == "verified" for s in station["streams"]):
            original_s = original[station["go_station_id"]]
            reasons = [outcomes[(station["go_station_id"], s["stream_id"])]["result"]
                       for s in station["streams"]]
            lacking.append({
                "go_station_id": station["go_station_id"],
                "name": station["display_name"],
                "legacy_aliases": station["legacy_aliases"],
                "known_previous_status": original_s["status"]["state"],
                "stream_reasons": reasons,
                "action": "retry_or_review_http_hls_tls_without_silent_deletion",
            })
    active = [s for s in rows if s["status"]["state"] == "active"]
    metadata = {
        "status": "FULL_SHORT_AUDIO_DECODER_EVIDENCE_UNSIGNED",
        "original_station_count": len(catalog["stations"]),
        "original_stream_count": len(all_streams),
        "probed_streams": len(refs),
        "decoded_streams_this_scan": errors["audio_decoded"],
        "failed_or_unresolved_streams": len(refs) - errors["audio_decoded"],
        "streams_marked_verified_after_scan": sum(
            stream["state"] == "verified"
            for _, stream in all_streams),
        "active_stations": len(active),
        "active_stations_with_a_verified_audio_stream":
            len(active) - len(lacking),
        "active_stations_without_a_verified_stream": lacking,
        "failure_reasons": dict(sorted((k, v) for k, v in errors.items()
                                       if k != "audio_decoded")),
        "source_test_pointer_sequence": 4,
        "draft_release_sequence": catalog["release_sequence"],
        "ready_to_sign": False,
        "publication_authorized": False,
        "note": "Bounded short decoded evidence, not long-term availability; no stream deleted; unsignable until separate admission/identity/asset rules are met.",
    }
    return result, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    for p in (args.out, args.summary):
        if p.exists():
            parser.error("refusing to overwrite a previous output")
    files = sorted(args.reports_dir.rglob("go-*.json"))
    if len(files) != 9:
        raise SystemExit(f"expected 9 exact live evidence reports, got {len(files)}")
    candidate = json.loads(args.catalog.read_text(encoding="utf-8"))
    updated, summary = merge(candidate, [json.loads(f.read_text(encoding="utf-8"))
                                          for f in files])
    args.out.write_text(json.dumps(updated, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({
        "probed":summary["probed_streams"],
        "decoded":summary["decoded_streams_this_scan"],
        "station_ready_with_audio":summary["active_stations_with_a_verified_audio_stream"],
        "station_without_decoded_stream":len(summary["active_stations_without_a_verified_stream"]),
        "signed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
