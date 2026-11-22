#!/usr/bin/env python3
"""Merge the 20-stream follow-up onto first-pass unsigned evidence.

Never signs or mutates a public catalog; fail closed on any identity, status,
stream URL, or original station mismatch. Keep all unavailable radios visible
in the candidate staging and report their exact reasons.
"""
from __future__ import annotations
import argparse
import copy
import json
from collections import Counter
from pathlib import Path


def combine(original: dict, first: dict, retry: dict):
    if first.get("release_sequence") != 5 or original.get("release_sequence") != 5:
        raise ValueError("wrong staging sequence")
    if retry.get("status") != "RETRY_UNRESOLVED_AUDIO_STREAMS_ONLY" or \
            retry.get("publication_authorized") is not False or \
            retry.get("signed") is not False or retry.get("no_removal") is not True:
        raise ValueError("untrusted follow-up evidence")
    rows = copy.deepcopy(first["stations"])
    source = original["stations"]
    if len(rows) != 320 or len(source) != 320:
        raise ValueError("unexpected migration coverage")
    if first.get("tombstones") != original.get("tombstones"):
        raise ValueError("retired identity changed")
    all_before = [(s, stream) for s in source for stream in s["streams"]]
    all_current = [(s, stream) for s in rows for stream in s["streams"]]
    if len(all_before) != 358 or len(all_current) != 358:
        raise ValueError("unexpected stream count")
    for old, new in zip(source, rows):
        old_identity = copy.deepcopy(old)
        new_identity = copy.deepcopy(new)
        for stream in old_identity["streams"]:
            stream.pop("state", None)
            stream.pop("last_checked_at", None)
        for stream in new_identity["streams"]:
            stream.pop("state", None)
            stream.pop("last_checked_at", None)
        if old_identity != new_identity:
            raise ValueError("unsigned original station metadata changed")
    seen = set()
    additional = 0
    recheck_reasons = Counter()
    failure_reasons_by_station = {}
    for rec in retry.get("rows", []):
        index = rec.get("index")
        if type(index) is not int or not 0 <= index < 358 or index in seen:
            raise ValueError("duplicate/invalid index")
        seen.add(index)
        previous_station, original_stream = all_before[index]
        current_station, current_stream = all_current[index]
        if (previous_station["go_station_id"] != rec.get("go_station_id") or
                current_station["go_station_id"] != rec.get("go_station_id")):
            raise ValueError("station identity mismatch")
        evidence = rec.get("retry")
        if not isinstance(evidence, dict):
            raise ValueError("missing retry proof")
        for key, expected in (("url", original_stream["url"]),
                              ("stream_id", original_stream["stream_id"]),
                              ("go_station_id", previous_station["go_station_id"])):
            if evidence.get(key) != expected:
                raise ValueError("stream identity or URL changed")
        if current_stream["state"] == "verified" or original_stream["state"] == "verified":
            raise ValueError("retrying a previously verified stream is not allowed")
        if evidence.get("verified") is True:
            if evidence.get("result") != "audio_decoded" or not evidence.get("checked_at"):
                raise ValueError("fictitious decoded evidence")
            current_stream["state"] = "verified"
            current_stream["last_checked_at"] = evidence["checked_at"]
            additional += 1
        elif evidence.get("verified") is False:
            reason = str(evidence.get("result"))
            recheck_reasons[reason] += 1
            failure_reasons_by_station.setdefault(current_station["go_station_id"], []).append(reason)
        else:
            raise ValueError("neither success nor explicit failure")
    if len(seen) != 20 or retry.get("attempts") != 20 or \
            retry.get("newly_decoded_on_retry") != additional:
        raise ValueError("incorrect retry coverage")
    actual = sum(stream["state"] == "verified" for _, stream in all_current)
    if actual != 338 + additional:
        raise ValueError("inconsistent decoded stream count")
    stranded = [
        {"go_station_id": s["go_station_id"], "name": s["display_name"],
         "legacy_aliases": s["legacy_aliases"],
         "stream_urls_preserved": len(s["streams"]),
         "reason_codes": failure_reasons_by_station.get(s["go_station_id"], [])}
        for s in rows
        if s["status"]["state"] == "active" and
        not any(st["state"] == "verified" for st in s["streams"])
    ]
    active = [s for s in rows if s["status"]["state"] == "active"]
    summary = {
        "scope": "UNSIGNED_GO_RADIO_358_SHORT_DECODER_PROOFS",
        "active": len(active),
        "active_with_decoded_stream": len(active) - len(stranded),
        "active_without_decoded_stream": stranded,
        "streams_decoded_initial": 338,
        "streams_recovered_on_retry": additional,
        "streams_decoded_cumulative": actual,
        "remaining_streams_not_decoded": 358 - actual,
        "last_retry_failure_reason_counts": dict(sorted(recheck_reasons.items())),
        "stations_not_deleted": len(rows) == len(source),
        "no_signed_publication": True,
        "caveat": "2s decoded prefix only; full Android playback/availability still untested",
    }
    updated = copy.deepcopy(first)
    updated["stations"] = rows
    return updated, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--original", required=True, type=Path)
    p.add_argument("--first", required=True, type=Path)
    p.add_argument("--retry", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--summary", required=True, type=Path)
    a = p.parse_args()
    for path in (a.out, a.summary):
        if path.exists():
            p.error("refuse to overwrite unsigned evidence")
    updated, report = combine(*[
        json.loads(path.read_text(encoding="utf-8")) for path in
        (a.original, a.first, a.retry)
    ])
    a.out.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    a.summary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "active_with_decoded_stream", "streams_decoded_cumulative",
        "remaining_streams_not_decoded", "no_signed_publication")}))
    for station in report["active_without_decoded_stream"]:
        print("UNRESOLVED", station["go_station_id"], station["name"],
              ", ".join(station["reason_codes"]))


if __name__ == "__main__":
    main()
