#!/usr/bin/env python3
"""Recheck only the 20 undecoded streams from the first 358-radio inventory run.

All sources are previously recorded historical URLs. No station is removed.
Supports HLS playlists through the bounded audio-only sample resolver.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from probe_full_radio_streams_20261122 import inspect_stream, installed_ffmpeg


def retry(catalog: dict, reports: list[dict], *, workers: int = 5) -> dict:
    if not 1 <= workers <= 8:
        raise ValueError("workers out of bounds")
    original_streams = [(s, stream) for s in catalog["stations"]
                        for stream in s["streams"]]
    if len(original_streams) != 358:
        raise ValueError("unexpected source inventory")
    observed = set()
    selected = []
    for report in reports:
        if report.get("publication_authorized") is not False or report.get("requested_streams") != 358:
            raise ValueError("untrusted initial evidence")
        offset = report.get("first_stream_index")
        if type(offset) is not int:
            raise ValueError("no original offset")
        for index, record in enumerate(report["rows"], offset):
            if index < 0 or index >= 358 or index in observed:
                raise ValueError("overlap/unknown stream index")
            observed.add(index)
            station, stream = original_streams[index]
            if (record.get("go_station_id"), record.get("stream_id"), record.get("url")) != (
                station["go_station_id"], stream["stream_id"], stream["url"]):
                raise ValueError("evidence doesn't match immutable original URL")
            if record["verified"] is False:
                selected.append((index, station, stream, record))
    if observed != set(range(358)):
        raise ValueError("first-pass reports did not cover every stream")
    if len(selected) != 20:
        raise ValueError("unexpected count of first-pass failed streams")

    checked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    executable = installed_ffmpeg()
    def run(item):
        index, station, stream, former = item
        result = inspect_stream(station["go_station_id"], stream, executable, checked)
        return {"index": index, "go_station_id": station["go_station_id"],
                "name": station["display_name"], "previous": former["result"],
                "retry": result}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run, selected))
    return {
        "status": "RETRY_UNRESOLVED_AUDIO_STREAMS_ONLY",
        "initial_inventory_stream_count": 358,
        "attempts": len(rows),
        "newly_decoded_on_retry": sum(x["retry"]["verified"] for x in rows),
        "still_unverified": [
            {"index": x["index"], "name": x["name"],
             "go_station_id": x["go_station_id"],
             "previous_reason": x["previous"],
             "new_reason": x["retry"]["result"]}
            for x in rows if x["retry"]["verified"] is False],
        "rows": rows,
        "publication_authorized": False,
        "signed": False,
        "no_removal": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", required=True, type=Path)
    p.add_argument("--evidence-dir", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    if args.report.exists():
        p.error("refusing to overwrite existing retry evidence")
    files = sorted(args.evidence_dir.rglob("go-*.json"))
    if len(files) != 9:
        raise ValueError(f"expected exactly 9 first-pass evidence files, found {len(files)}")
    result = retry(json.loads(args.catalog.read_text(encoding="utf-8")),
                   [json.loads(f.read_text(encoding="utf-8")) for f in files])
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n",
                           encoding="utf-8")
    print(json.dumps({"retry_attempts":result["attempts"],
                      "newly_decoded":result["newly_decoded_on_retry"],
                      "still_unverified":len(result["still_unverified"]),
                      "publication_authorized":False}))
    for row in result["still_unverified"]:
        print(row["go_station_id"], row["name"], ":", row["new_reason"])


if __name__ == "__main__":
    main()
