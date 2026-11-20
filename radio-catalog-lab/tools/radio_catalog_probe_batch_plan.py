#!/usr/bin/env python3
"""Bounded, fair, NON-PUBLISHING MP3/AAC probing plan for Grosses Ondes.

The report contains only UUIDs and hashes. Optional real probe inputs containing
stream URLs are written *only* to an explicit, new, non-repository scratch folder.
No network calls, scheduled operations or editorial changes happen here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from radio_catalog_daily_candidate_reconcile import checked_uuid, load_json
from radio_catalog_qualification_queue import build_queue, fingerprint

EPOCH = dt.date(2026, 11, 20)
MAX_PER_PROBE = 5
MAX_DAILY_PROBES = 40


def _pick_pool(items: list[dict], *, date: dt.date, count: int,
               used: set[str]) -> list[dict]:
    """Rotate across all stream hashes; avoid repeat station UUIDs in a day."""
    if count <= 0 or not items:
        return []
    items = sorted(items, key=lambda x: (
        x["stationuuid"], x["streamSha256"], x["goStationId"] or ""))
    start = ((date - EPOCH).days * count) % len(items)
    selected = []
    for index in range(len(items)):
        row = items[(start + index) % len(items)]
        uid = row["stationuuid"]
        if uid in used:
            continue
        used.add(uid)
        selected.append(row)
        if len(selected) >= count:
            break
    return selected


def plan_batches(catalog: dict, discovery: dict, *, day: str,
                 max_daily: int = MAX_DAILY_PROBES,
                 max_per_batch: int = MAX_PER_PROBE) -> dict:
    today = dt.date.fromisoformat(day)
    if today.isoformat() != day:
        raise ValueError("Noncanonical schedule date")
    if not 1 <= max_daily <= MAX_DAILY_PROBES:
        raise ValueError("Daily probe budget exceeded")
    if not 1 <= max_per_batch <= MAX_PER_PROBE:
        raise ValueError("Single probe budget exceeded")
    queue = build_queue(catalog, discovery)
    eligible = [
        r for r in queue["items"]
        if r["transportLane"] == "mp3_aac_first" and r["streamSha256"]
        and r["stationuuid"]
    ]
    historic = [r for r in eligible if r["source"] == "historical"]
    found = [r for r in eligible if r["source"] == "discovery"]
    used: set[str] = set()
    # Reserve up to 20% for daily discoveries, even with a full legacy backlog.
    new_capacity = min(len(found), max(1, max_daily // 5)) if found else 0
    old_capacity = max_daily - new_capacity
    selected_old = _pick_pool(historic, date=today, count=old_capacity, used=used)
    selected_new = _pick_pool(found, date=today, count=max_daily - len(selected_old),
                              used=used)
    # If discovery has fewer than its quota (or overlaps old UUIDs), fill
    # spare capacity with historical variants, still unique by UUID per day.
    additional_old = _pick_pool(historic, date=today,
                                count=max_daily - len(selected_old) - len(selected_new),
                                used=used)
    selected = selected_old + selected_new + additional_old
    batches = []
    for start in range(0, len(selected), max_per_batch):
        batch = selected[start:start + max_per_batch]
        batches.append({
            "batchNumber": len(batches) + 1,
            "candidateCount": len(batch),
            "candidates": [{
                "stationuuid": r["stationuuid"],
                "goStationId": r["goStationId"],
                "streamSha256": r["streamSha256"],
                "source": r["source"],
                "identityStatus": r["identityStatus"],
            } for r in batch],
        })
    return {
        "schemaVersion": 1,
        "scanDate": day,
        "sourceCandidateCount": queue["discoveredCandidateCount"],
        "historicalStreamCount": queue["preservedHistoricalStreamCount"],
        "eligibleDirectStreamCount": len(eligible),
        "plannedProbeCount": len(selected),
        "plannedHistoricalCount": len(selected_old) + len(additional_old),
        "plannedDiscoveryCount": len(selected_new),
        "unaddressedFormatCount": queue["transportLaneCounts"]["other_needs_format_check"],
        "separateHlsCount": queue["transportLaneCounts"]["hls_deferred"],
        "skippedWithoutUuidCount": sum(
            r["transportLane"] == "mp3_aac_first" and not r["stationuuid"]
            for r in queue["items"]),
        "safety": {
            "networkEnabled": False,
            "automaticPublicationAllowed": False,
            "technicalQualificationGranted": False,
            "oldStationsDeleted": 0,
            "maxProbesPerBatch": max_per_batch,
            "maxProbesPerDay": max_daily,
        },
        "batches": batches,
    }


def _url_index(catalog: dict, discovery: dict) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for station in catalog["stations"]:
        ids = [checked_uuid(x["uuid"] if isinstance(x, dict) else x)
               for x in station.get("radio_browser_uuids", [])]
        ids.extend(checked_uuid(x) for x in station.get("legacy_aliases", []))
        for stream in station.get("streams", []):
            url = stream.get("url")
            sha = fingerprint(url)
            if sha:
                for uid in ids:
                    result.setdefault((uid, sha), url)
    for c in discovery["candidates"]:
        uid = checked_uuid(c["stationuuid"])
        url = c.get("streamUrl")
        sha = fingerprint(url)
        if sha:
            result.setdefault((uid, sha), url)
    return result


def write_temporary_probe_inputs(
    plan: dict, catalog: dict, discovery: dict, folder: Path,
    *, workspace: Path | None = None,
) -> None:
    """Never place stream URLs in a Git checkout or reusable artifact folder."""
    resolved = folder.resolve()
    worktree = (workspace or Path.cwd()).resolve()
    if resolved == worktree or worktree in resolved.parents:
        raise ValueError("Temporary stream URLs cannot be stored in a checkout")
    if folder.exists():
        raise ValueError("Refusing existing scratch directory")
    sources = _url_index(catalog, discovery)
    # Resolve every reference *before* creating any files.
    payloads = []
    for batch in plan["batches"]:
        rows = []
        for entry in batch["candidates"]:
            key = (entry["stationuuid"], entry["streamSha256"])
            if key not in sources:
                raise ValueError("Stale or forged batch stream fingerprint")
            rows.append({
                "stationuuid": entry["stationuuid"],
                "name": entry["goStationId"] or "candidate",
                "status": "needs_stream_check",
                "streamUrl": sources[key],
            })
        payloads.append({
            "schemaVersion": 1,
            "scanDate": plan["scanDate"],
            "publicationAllowed": False,
            "candidates": rows,
        })
    folder.mkdir(mode=0o700, parents=False)
    os.chmod(folder, 0o700)
    for index, payload in enumerate(payloads, start=1):
        output = folder / f"probe-batch-{index:02d}.json"
        handle = os.open(str(output), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as writer:
            json.dump(payload, writer, ensure_ascii=False)
            writer.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--date", default=dt.datetime.now(dt.timezone.utc).date().isoformat())
    parser.add_argument("--max-daily", type=int, default=40)
    parser.add_argument("--max-per-batch", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-probe-inputs", type=Path,
                        help="Private ephemeral directory OUTSIDE checkout; contains raw stream URLs")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite a previous scheduling report")
    catalog, discovery = load_json(args.catalog), load_json(args.discovery)
    report = plan_batches(catalog, discovery, day=args.date,
                          max_daily=args.max_daily, max_per_batch=args.max_per_batch)
    if args.scratch_probe_inputs:
        write_temporary_probe_inputs(report, catalog, discovery, args.scratch_probe_inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print("RADIO_BATCH_PLAN_OFFLINE"
          f" direct={report['eligibleDirectStreamCount']}"
          f" historical={report['plannedHistoricalCount']}"
          f" new={report['plannedDiscoveryCount']}"
          f" batches={len(report['batches'])}"
          " qualified=0 published=false")


if __name__ == "__main__":
    main()
