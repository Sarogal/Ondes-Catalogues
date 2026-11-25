#!/usr/bin/env python3
"""Second pass: compare ICY samples to existing GoNowPlaying separator rules.

Only the authenticated catalog can supply URLs for repeat probes. First-pass
observations are evidence, not app display or artist identity verification.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from go_radio_v8_public_verifier import EXPECTED_V8, verify_remote
from go_radio_v8_metadata_probe import worker


def format_kind(raw, station_name):
    raw = " ".join(raw.split())
    if not raw:
        return "empty"
    if raw.casefold() == " ".join(station_name.split()).casefold():
        return "station_name_only"
    for sep in (" - ", " – ", " — "):
        left, found, right = raw.partition(sep)
        if found and left.strip() and right.strip():
            return "current_parser_pair"
    for sep in (" | ", " : ", " / ", " ~ "):
        left, found, right = raw.partition(sep)
        if found and left.strip() and right.strip():
            return "alternative_separator_candidate"
    return "unsplit"


def kinds(evidence, name):
    return [format_kind(t["raw"], name) for t in evidence.get("titles", [])
            if isinstance(t, dict) and isinstance(t.get("raw"), str)]


def run(source, output, workers):
    _, catalog = verify_remote()
    active = {s["go_station_id"]: s for s in catalog["stations"]
              if s["status"]["state"] == "active"}
    data = json.loads(source.read_text(encoding="utf-8"))
    if data["signed_sequence"] != 8 or data["catalog_sha256"] != EXPECTED_V8:
        raise ValueError("Evidence belongs to another catalog")
    previous = {s["go_station_id"]: s for s in data["stations"]}
    if set(previous) != set(active) or len(data["stations"]) != len(active):
        raise ValueError("First pass missing or duplicated stations")
    rows, jobs = [], []
    for gid, station in active.items():
        name = station["display_name"]
        old = previous[gid]["streams"]
        by_id = {s["stream_id"]: s for s in old}
        signed = station["streams"]
        if len(old) != len(by_id) or set(by_id) != {s["stream_id"] for s in signed}:
            raise ValueError("First pass has missing or duplicated variants")
        row = {"go_station_id": gid, "name": name, "homepage": station.get("homepage"),
               "classification": "E", "streams": []}
        rows.append(row)
        for stream in signed:
            first = by_id[stream["stream_id"]]
            if first["url"] != stream["url"]:
                raise ValueError("First-pass stream URL does not match signature")
            record = {"stream_id": stream["stream_id"], "url": stream["url"],
                      "priority": stream.get("priority"), "first": first,
                      "first_formats": kinds(first, name)}
            row["streams"].append(record)
            if first["observation"] != "icy_title_observed" or not (
                    "current_parser_pair" in record["first_formats"]):
                jobs.append((name, record))
    locks = {urlsplit(r["url"]).hostname: threading.BoundedSemaphore(2) for _, r in jobs}

    def guarded(job):
        name, record = job
        with locks[urlsplit(record["url"]).hostname]:
            evidence = worker(record["url"])
        record["repeat"] = evidence
        record["repeat_formats"] = kinds(evidence, name)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(guarded, jobs))

    station_counts, stream_counts, first_formats = Counter(), Counter(), Counter()
    unresolved = []
    for row in rows:
        labels = set()
        for record in row["streams"]:
            first_formats.update(record["first_formats"])
            formats = record["first_formats"] + record.get("repeat_formats", [])
            labels.update(formats)
            if "current_parser_pair" in formats:
                stream_counts["current_parser_pair_candidate"] += 1
            elif "alternative_separator_candidate" in formats:
                stream_counts["alternative_separator_candidate"] += 1
            elif formats:
                stream_counts["unsplit_or_station_label"] += 1
            else:
                stream_counts["no_nonempty_icy_title_observed"] += 1
        if "current_parser_pair" in labels:
            kind = "current_parser_pair_candidate"
        elif "alternative_separator_candidate" in labels:
            kind = "alternative_separator_candidate"
        elif labels:
            kind = "unsplit_or_station_label"
        else:
            kind = "no_nonempty_icy_title_observed"
        row["format_evidence"] = kind
        station_counts[kind] += 1
        if kind != "current_parser_pair_candidate":
            unresolved.append({"id": row["go_station_id"], "name": row["name"], "kind": kind})
    summary = {"station_count": len(rows), "stream_count": sum(stream_counts.values()),
               "repeat_probes": len(jobs), "first_title_formats": dict(first_formats),
               "station_format_evidence": dict(station_counts),
               "stream_format_evidence": dict(stream_counts), "unresolved": unresolved,
               "classification_note": "All E pending app comparison; separator pairs are not verified artist identities."}
    output.write_text(json.dumps({"signed_sequence": 8, "catalog_sha256": EXPECTED_V8,
                                  "summary": summary, "stations": rows},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=6)
    args = parser.parse_args()
    run(args.first, args.output, args.workers)
