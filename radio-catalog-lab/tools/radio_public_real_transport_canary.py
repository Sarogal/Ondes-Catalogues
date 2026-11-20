#!/usr/bin/env python3
"""One-shot public Radio Browser live MP3/AAC probe canary (max 5, no publisher).

This tests the real transport on PUBLIC directory candidates ONLY. It does
NOT establish that any historical private Grosses Ondes radio was checked.
Raw audio URLs stay inside the runner's ephemeral private scratch directory.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from typing import Callable

from radio_catalog_probe_batch_plan import plan_batches, write_temporary_probe_inputs
from radio_catalog_batch_evidence_bridge import consume_batches
from radio_daily_discovery import candidate, fetch_page, resolve_api_mirrors
from radio_stream_technical_probe import PinnedHttpTransport, ResponseSample, probe_candidates

MAX_LIVE = 5
MAX_DIRECTORY = 100


def qualify_public_candidates(rows: list[dict], *, day: str,
                              request: Callable[[str], ResponseSample],
                              scratch_parent: Path) -> tuple[dict, dict]:
    """Use the actual (untrusted) Radio Browser codec tag, never fake a format."""
    if not isinstance(rows, list) or len(rows) > MAX_DIRECTORY:
        raise ValueError("Unexpected public radio directory response size")
    found = []
    seen = set()
    for raw in rows:
        row = candidate(raw, set())
        if row is None or row["status"] == "needs_duplicate_review":
            continue
        codec = str(raw.get("codec") or "").lower()
        stream = row.get("streamUrl") or ""
        if ("mp3" not in codec and "aac" not in codec
                and not stream.lower().split("?", 1)[0].endswith((".mp3", ".aac"))):
            continue
        if stream.lower().split("?", 1)[0].endswith(".m3u8"):
            continue
        uid = row["stationuuid"]
        if uid in seen or not stream:
            continue
        seen.add(uid)
        row["codec"] = str(raw.get("codec") or "")[:60]
        found.append(row)
    # First 5 eligible from the current latest directory page; no UUID allowlist.
    selected = found[:MAX_LIVE]
    if len(selected) < MAX_LIVE:
        raise ValueError("Insufficient independent public MP3/AAC candidates for live canary")
    discovered = {
        "schemaVersion": 1, "scanDate": day,
        "publicationAllowed": False, "candidates": selected,
    }
    synthetic_empty = {"schema_version": 1, "stations": [], "tombstones": []}
    plan = plan_batches(
        synthetic_empty, discovered, day=day,
        max_daily=MAX_LIVE, max_per_batch=MAX_LIVE,
    )
    if (plan["plannedProbeCount"] != MAX_LIVE
            or plan["plannedDiscoveryCount"] != MAX_LIVE
            or len(plan["batches"]) != 1):
        raise ValueError("Refusing incomplete public transport canary")
    with tempfile.TemporaryDirectory(
        prefix="go-public-probe-urls-", dir=str(scratch_parent),
    ) as tmp:
        private_raw = Path(tmp) / "ephemeral-url-input"
        write_temporary_probe_inputs(
            plan, synthetic_empty, discovered, private_raw, workspace=Path.cwd(),
        )
        probe_input = json.loads(
            (private_raw / "probe-batch-01.json").read_text(encoding="utf-8"))
        report = probe_candidates(
            probe_input, request, limit=MAX_LIVE,
            observation_day=dt.date.fromisoformat(day),
        )
        result = consume_batches(plan, [report])
    counts = dict(sorted(collections.Counter(
        c["verdict"] for c in report["checks"]).items()))
    summary = {
        "schemaVersion": 1,
        "kind": "public_directory_live_transport_canary_not_private_historical",
        "observationDate": day,
        "discoveredDirectoryPageSize": len(rows),
        "eligibleDirectCandidatesOnPage": len(found),
        "actualNetworkProbes": result["processedChecks"],
        "audioSampleEvidenceCount": result["audioSampleObservations"],
        "verdictCounts": counts,
        "historicalPrivateStationsChecked": 0,
        "technicallyQualifiedCount": 0,
        "editorialApprovals": 0,
        "oldStationsDeleted": 0,
        "publicationAllowed": False,
        "multiDayProofRequired": True,
    }
    for item in (summary, result["streamEvidence"]):
        serialized = json.dumps(item, ensure_ascii=False)
        if "http://" in serialized or "https://" in serialized or "streamUrl" in serialized:
            raise ValueError("Leaked URL in report")
    return summary, result["streamEvidence"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    if not args.allow_network:
        parser.error("External network access requires --allow-network")
    if (os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_REF_NAME") !=
            "feature/radio-release1-public-live-transport-canary-20261120"):
        parser.error("Only the isolated GitHub feature branch can run this one-shot canary")
    destination = args.output_dir.resolve()
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    if destination.exists() or destination == workspace or workspace in destination.parents:
        parser.error("Output directory must be new and outside Git working tree")
    destination.mkdir(mode=0o700, parents=False)
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    hosts = resolve_api_mirrors()
    # Exactly one read-only directory request; station URLs are still untrusted.
    rows = fetch_page(hosts, "tag", "metal", offset=0, limit=MAX_DIRECTORY)
    summary, ledger = qualify_public_candidates(
        rows, day=day, request=PinnedHttpTransport().request,
        scratch_parent=destination,
    )
    with (destination / "live-canary-summary.json").open("x", encoding="utf-8") as writer:
        json.dump(summary, writer, indent=2, ensure_ascii=False)
        writer.write("\n")
    with (destination / "live-canary-ledger.json").open("x", encoding="utf-8") as writer:
        json.dump(ledger, writer, indent=2, ensure_ascii=False)
        writer.write("\n")
    # Never print station URLs, names or raw audio.
    print("GO_PUBLIC_REAL_RADIO_TRANSPORT_CANARY"
          f" directory_page={summary['discoveredDirectoryPageSize']}"
          f" eligible_direct={summary['eligibleDirectCandidatesOnPage']}"
          f" checked={summary['actualNetworkProbes']}"
          f" audio_samples={summary['audioSampleEvidenceCount']}"
          f" verdicts={summary['verdictCounts']}"
          " historical_private_checked=0 certified=0 published=false")


if __name__ == "__main__":
    main()
