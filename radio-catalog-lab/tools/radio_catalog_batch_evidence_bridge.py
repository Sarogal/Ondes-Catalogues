#!/usr/bin/env python3
"""Offline bridge: exact Release-1 probe batches -> opt-in per-stream evidence.

Validates reports produced by the EXISTING secure stream probe, rather than
implementing another transport. No URL fetching, admission, signing or publish.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from radio_catalog_daily_candidate_reconcile import checked_uuid, load_json
from radio_stream_recheck_ledger import next_evidence_report

SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_DAILY = 40
MAX_BATCH = 5
MAX_BATCHES = 8


def consume_batches(plan: dict, reports: list[dict], previous: dict | None = None) -> dict:
    if not isinstance(plan, dict) or plan.get("schemaVersion") != 1:
        raise ValueError("Invalid Release-1 batch plan")
    date = plan.get("scanDate")
    if not isinstance(date, str) or dt.date.fromisoformat(date).isoformat() != date:
        raise ValueError("Invalid schedule date")
    safety = plan.get("safety")
    if (not isinstance(safety, dict) or safety.get("networkEnabled") is not False
            or safety.get("automaticPublicationAllowed") is not False
            or safety.get("technicalQualificationGranted") is not False
            or safety.get("oldStationsDeleted") != 0
            or safety.get("maxProbesPerBatch") not in range(1, MAX_BATCH + 1)
            or safety.get("maxProbesPerDay") not in range(1, MAX_DAILY + 1)):
        raise ValueError("Unsafe batch plan")
    batches = plan.get("batches")
    if (not isinstance(batches, list) or len(batches) > MAX_BATCHES
            or not isinstance(reports, list) or len(reports) != len(batches)):
        raise ValueError("Missing, excessive or mismatched batch reports")

    observed: set[str] = set()
    expected_total = 0
    evidence = previous
    audio_count = 0
    for index, (batch, report) in enumerate(zip(batches, reports), 1):
        if not isinstance(batch, dict) or batch.get("batchNumber") != index:
            raise ValueError("Bad batch number or ordering")
        refs = batch.get("candidates")
        if (not isinstance(refs, list) or len(refs) > MAX_BATCH
                or batch.get("candidateCount") != len(refs)):
            raise ValueError("Invalid batch candidates")
        expected: dict[str, str] = {}
        for item in refs:
            if not isinstance(item, dict) or item.get("source") not in ("historical", "discovery"):
                raise ValueError("Invalid candidate source")
            uid = checked_uuid(item.get("stationuuid"))
            sha = item.get("streamSha256")
            if not isinstance(sha, str) or SHA.fullmatch(sha) is None:
                raise ValueError("Missing exact stream hash")
            if uid in observed:
                raise ValueError("Candidate UUID scheduled more than once today")
            observed.add(uid)
            expected[uid] = sha
        if (not isinstance(report, dict) or report.get("schemaVersion") != 1
                or report.get("observationDate") != date
                or report.get("publicationAllowed") is not False
                or report.get("technicalVerifiedCount") != 0
                or not isinstance(report.get("checks"), list)
                or report.get("checkedCount") != len(report["checks"])
                or len(report["checks"]) != len(expected)):
            raise ValueError("Incomplete or untrusted probe batch report")
        received = {}
        for check in report["checks"]:
            if not isinstance(check, dict) or check.get("publicationAllowed") is not False:
                raise ValueError("Untrusted individual stream check")
            if any(field in check for field in ("url", "streamUrl", "audioBytes", "body")):
                raise ValueError("Probe evidence must not contain raw URLs or audio")
            uid = checked_uuid(check.get("stationuuid"))
            sha = check.get("streamSha256")
            if uid in received or expected.get(uid) != sha:
                raise ValueError("Probe result does not match scheduled stream fingerprint")
            received[uid] = check
        if received.keys() != expected.keys():
            raise ValueError("A scheduled radio is missing from probe evidence")
        good = sum(c.get("verdict") == "audio_sample_ok" for c in received.values())
        if report.get("audioEvidenceCount") != good:
            raise ValueError("Claimed audio sample count does not match checks")
        expected_total += len(refs)
        audio_count += good
        # Uses the validated PR #517 ledger, preserving separate stream SHA
        # records. Reports remain non-certifying, including repeated success.
        evidence = next_evidence_report(
            report, evidence, retain_stream_variants=True,
        )
    if (plan.get("plannedProbeCount") != expected_total or
            expected_total > safety["maxProbesPerDay"] or
            expected_total > MAX_DAILY):
        raise ValueError("Planned probe count does not match bounded batches")
    if evidence is None:
        # Empty plans do not fabricate an evidence record.
        evidence = next_evidence_report({
            "schemaVersion": 1, "observationDate": date,
            "publicationAllowed": False, "checks": [],
        }, previous, retain_stream_variants=True)
    if evidence.get("streamHistoryMode") != "per_stream":
        raise ValueError("Multi-stream ledger unavailable")
    if evidence.get("technicallyQualifiedCount") != 0 or evidence.get("publicationAllowed") is not False:
        raise ValueError("Unexpected technical qualification or publishing state")
    return {
        "schemaVersion": 1,
        "observationDate": date,
        "processedBatches": len(batches),
        "processedChecks": expected_total,
        "audioSampleObservations": audio_count,
        "technicallyQualifiedCount": 0,
        "automaticallyApprovedCount": 0,
        "publicationAllowed": False,
        "streamEvidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--batch-report", type=Path, action="append", default=[])
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-output", type=Path,
                        help="Standalone multi-stream ledger for next day's --previous")
    args = parser.parse_args()
    if args.output.exists() or (args.ledger_output and args.ledger_output.exists()):
        parser.error("Refusing to overwrite existing report or ledger")
    if args.ledger_output and args.output.resolve() == args.ledger_output.resolve():
        parser.error("Report and standalone ledger output must be different")
    result = consume_batches(
        load_json(args.plan), [load_json(p) for p in args.batch_report],
        load_json(args.previous) if args.previous else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.ledger_output:
        args.ledger_output.parent.mkdir(parents=True, exist_ok=True)
        with args.ledger_output.open("x", encoding="utf-8") as writer:
            writer.write(json.dumps(result["streamEvidence"], ensure_ascii=False, indent=2) + "\n")
    with args.output.open("x", encoding="utf-8") as writer:
        writer.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("RADIO_BATCH_EVIDENCE_OFFLINE"
          f" batches={result['processedBatches']}"
          f" checks={result['processedChecks']}"
          f" samples={result['audioSampleObservations']}"
          " qualified=0 published=false")


if __name__ == "__main__":
    main()
