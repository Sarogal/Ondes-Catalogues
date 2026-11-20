#!/usr/bin/env python3
"""Append-only preview of repeat audio evidence on separate UTC dates.

This is *NOT* a playable-stream certification, a publisher, or a deletion engine.
An observed MP3/Ogg/FLAC header can be a recording rather than live radio.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

VALID_VERDICTS = frozenset({
    "audio_sample_ok", "audio_mime_only", "playlist_pending",
    "not_confirmed_audio", "needs_review", "blocked_unsafe",
})
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def parse_day(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("Invalid observation day")
    day = dt.date.fromisoformat(raw).isoformat()
    if day != raw:
        raise ValueError("Non-canonical observation day")
    return day


def valid_uuid(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("Invalid station UUID")
    value = str(uuid.UUID(raw))
    if value != raw:
        raise ValueError("Non-canonical station UUID")
    return value


def next_evidence_report(probe: dict, previous: dict | None = None) -> dict:
    if (not isinstance(probe, dict) or probe.get("schemaVersion") != 1 or
        probe.get("publicationAllowed") is not False or
        not isinstance(probe.get("checks"), list)):
        raise ValueError("Untrusted technical probe report")
    day = parse_day(probe.get("observationDate"))
    checks = probe["checks"]
    if len(checks) > 5:
        raise ValueError("Probe count exceeds isolated budget")
    records: dict[str, dict] = {}
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get("schemaVersion") != 1 or
            previous.get("publicationAllowed") is not False or
            not isinstance(previous.get("records"), list)):
            raise ValueError("Invalid previous evidence report")
        for row in previous["records"]:
            if not isinstance(row, dict):
                raise ValueError("Invalid previous record")
            uid = valid_uuid(row.get("stationuuid"))
            sha = row.get("streamSha256")
            if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
                raise ValueError("Invalid previous stream fingerprint")
            dates = row.get("audioEvidenceDates")
            if not isinstance(dates, list) or len(dates) > 30:
                raise ValueError("Bad previous observation count")
            dates = [parse_day(value) for value in dates]
            if dates != sorted(set(dates)) or any(value > day for value in dates):
                raise ValueError("Invalid previous evidence days")
            last = parse_day(row.get("lastObservedDate"))
            if last > day or uid in records:
                raise ValueError("Future or repeated evidence record")
            records[uid] = {
                "stationuuid": uid,
                "streamSha256": sha,
                "audioEvidenceDates": dates,
                "lastObservedDate": last,
                "lastVerdict": str(row.get("lastVerdict") or ""),
            }
    seen = set()
    for item in checks:
        if not isinstance(item, dict) or item.get("publicationAllowed") is not False:
            raise ValueError("Unsafe or invalid probe result")
        uid = valid_uuid(item.get("stationuuid"))
        if uid in seen:
            raise ValueError("Duplicate probe UUID")
        seen.add(uid)
        verdict = item.get("verdict")
        sha = item.get("streamSha256")
        if verdict not in VALID_VERDICTS or not isinstance(sha, str) or (
            not SHA256_RE.fullmatch(sha)
        ):
            raise ValueError("Unknown verdict or stream fingerprint")
        old = records.get(uid)
        if old is None or old["streamSha256"] != sha:
            old = {
                "stationuuid": uid, "streamSha256": sha,
                "audioEvidenceDates": [], "lastObservedDate": day,
                "lastVerdict": verdict,
            }
            records[uid] = old
        old["lastVerdict"] = verdict
        old["lastObservedDate"] = day
        if verdict == "audio_sample_ok" and day not in old["audioEvidenceDates"]:
            old["audioEvidenceDates"] = sorted(
                (old["audioEvidenceDates"] + [day])[-30:])
    output_rows = []
    for uid, row in sorted(records.items()):
        # Repeat evidence is a prompt for extended live-radio checks, not
        # a stamp that a station plays music continuously or can be published.
        output_rows.append({
            **row,
            "repeatAudioSample": (
                len(row["audioEvidenceDates"]) >= 2
                and row["lastObservedDate"] == day
                and row["lastVerdict"] == "audio_sample_ok"
            ),
            "technicalQualified": False,
            "publicationAllowed": False,
        })
    return {
        "schemaVersion": 1, "observationDate": day,
        "publicationAllowed": False, "technicallyQualifiedCount": 0,
        "repeatAudioCandidateCount": sum(
            x["repeatAudioSample"] for x in output_rows),
        "notObservedTodayCount": sum(
            x["lastObservedDate"] != day for x in output_rows),
        "records": output_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    previous = (json.loads(args.previous.read_text(encoding="utf-8"))
                if args.previous else None)
    report = next_evidence_report(probe, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("RADIO_STREAM_EVIDENCE_PREVIEW_ONLY "
          f"repeat_sample_candidates={report['repeatAudioCandidateCount']} "
          f"retained_unseen={report['notObservedTodayCount']} "
          "qualified=0 published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
