#!/usr/bin/env python3
"""Prepare a NON-PUBLISHING release-1 stream qualification queue.

Reuses the existing central identity reconciler. It does not call the network,
trust a Radio Browser success flag, change a GO ID, or approve/remove a station.
Legacy MP3/AAC candidates are scheduled ahead of complex HLS candidates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from radio_catalog_daily_candidate_reconcile import (
    checked_uuid, index_catalog, load_json, review_candidates,
)

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ROWS = 25000


def media_class(codec: object, raw_url: object, protocol: object = None) -> str:
    name = str(codec or "").strip().lower()
    scheme = str(protocol or "").strip().lower()
    path = urlsplit(raw_url).path.lower() if isinstance(raw_url, str) else ""
    if "hls" in name or "hls" in scheme or path.endswith(".m3u8"):
        return "hls_deferred"
    if any(value in name for value in ("mp3", "mpeg", "aac")) or path.endswith((".mp3", ".aac")):
        return "mp3_aac_first"
    return "other_needs_format_check"


def fingerprint(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    if len(raw) > 2048 or any(ord(c) < 32 for c in raw):
        raise ValueError("Invalid stream URL in input")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evidence_index(document: dict | None) -> dict[tuple[str, str], dict]:
    if document is None:
        return {}
    if (not isinstance(document, dict) or document.get("schemaVersion") != 1
            or document.get("publicationAllowed") is not False
            or document.get("technicallyQualifiedCount") != 0
            or not isinstance(document.get("records"), list)):
        raise ValueError("Unsafe technical evidence ledger")
    if len(document["records"]) > MAX_ROWS:
        raise ValueError("Excessive technical evidence rows")
    observed = dt.date.fromisoformat(document["observationDate"])
    result = {}
    for row in document["records"]:
        if (not isinstance(row, dict) or row.get("publicationAllowed") is not False
                or row.get("technicalQualified") is not False):
            raise ValueError("Technical evidence cannot authorize publication")
        uid = checked_uuid(row.get("stationuuid"))
        sha = row.get("streamSha256")
        if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
            raise ValueError("Invalid stream fingerprint")
        dates = {}
        for key in ("audioEvidenceDates", "sustainedTransportDates",
                    "frameChainDates", "decodedPcmDates"):
            data = row.get(key, [])
            if not isinstance(data, list) or len(data) > 30:
                raise ValueError("Invalid evidence days")
            parsed = [dt.date.fromisoformat(x).isoformat() for x in data]
            if parsed != sorted(set(parsed)) or any(
                    dt.date.fromisoformat(x) > observed for x in parsed):
                raise ValueError("Duplicated, unordered or future evidence days")
            dates[key] = set(parsed)
        if (not dates["decodedPcmDates"].issubset(dates["sustainedTransportDates"])
                or not dates["frameChainDates"].issubset(dates["sustainedTransportDates"])
                or not dates["sustainedTransportDates"].issubset(dates["audioEvidenceDates"])):
            raise ValueError("Inconsistent evidence hierarchy")
        key = (uid, sha)
        if key in result:
            raise ValueError("Duplicate technical evidence")
        result[key] = {
            "audioDays": len(dates["audioEvidenceDates"]),
            "sustainedDays": len(dates["sustainedTransportDates"]),
            "frameDays": len(dates["frameChainDates"]),
            "decodedDays": len(dates["decodedPcmDates"]),
        }
    return result


def _counts(catalog: dict, discovery: dict) -> None:
    if (not isinstance(catalog, dict) or catalog.get("schema_version") != 1
            or not isinstance(catalog.get("stations"), list)
            or not isinstance(discovery, dict) or discovery.get("schemaVersion") != 1
            or discovery.get("publicationAllowed") is not False
            or not isinstance(discovery.get("candidates"), list)):
        raise ValueError("Unexpected catalog/discovery input")


def build_queue(catalog: dict, discovery: dict,
                technical: dict | None = None,
                extra_known_ids: set[str] | None = None) -> dict:
    _counts(catalog, discovery)
    if len(catalog["stations"]) + len(discovery["candidates"]) > MAX_ROWS:
        raise ValueError("Queue input too large")
    owners, _, _ = index_catalog(catalog)  # Detect conflicting legacy UUIDs.
    reconciled = review_candidates(catalog, discovery, extra_known_ids)
    by_uuid = {row["stationuuid"]: row for row in reconciled["candidates"]}
    proof = evidence_index(technical)
    queue = []
    seen_go = set()

    def append(*, uid: str | None, go_id: str | None, source: str, identity: str,
               raw_url: object, codec: object, protocol: object = None,
               duplicate_risk: bool = False) -> None:
        sha = fingerprint(raw_url)
        category = media_class(codec, raw_url, protocol)
        evidence = proof.get((uid, sha), {}) if uid and sha else {}
        if category == "hls_deferred":
            action, priority = "separate_hls_verification_lane", 4 if source == "historical" else 5
        elif category == "mp3_aac_first":
            action, priority = "bounded_multiday_mp3_aac_probes", 0 if source == "historical" else 1
        else:
            action, priority = "determine_audio_format_safely", 2 if source == "historical" else 3
        if not sha:
            action = "recover_stream_url_without_deletion"
        if evidence.get("decodedDays", 0) >= 2:
            action = "review_multi_day_pcm_and_station_identity"
        elif evidence.get("sustainedDays", 0) >= 2:
            action = "review_multi_day_sustained_audio_and_identity"
        if duplicate_risk or identity in ("possible_variant_or_duplicate", "known_legacy_not_yet_mapped"):
            # Identity conflicts remain independently reviewable even when audio plays.
            action += "_plus_identity_review"
        queue.append({
            "stationuuid": uid,
            "goStationId": go_id,
            "source": source,
            "identityStatus": identity,
            "streamSha256": sha,
            "transportLane": category,
            "nextAction": action,
            "priority": priority,
            "audioEvidenceDays": evidence.get("audioDays", 0),
            "sustainedEvidenceDays": evidence.get("sustainedDays", 0),
            "decodedEvidenceDays": evidence.get("decodedDays", 0),
            "technicalQualified": False,
            "editoriallyApproved": False,
            "publicationAllowed": False,
        })

    # All historical GO records are retained, including ones absent from today's discovery.
    for station in catalog["stations"]:
        go_id = station.get("go_station_id")
        if not isinstance(go_id, str) or not go_id or go_id in seen_go:
            raise ValueError("Invalid or duplicate GO station identity")
        seen_go.add(go_id)
        streams = station.get("streams")
        if not isinstance(streams, list):
            raise ValueError("Historical stream list missing")
        uuids = [checked_uuid(x["uuid"] if isinstance(x, dict) else x)
                 for x in station.get("radio_browser_uuids", [])]
        uuids += [checked_uuid(x) for x in station.get("legacy_aliases", [])]
        # Technical ledgers associate stream SHA to UUID; only use a matching pair.
        for stream in streams:
            if not isinstance(stream, dict):
                raise ValueError("Invalid historical stream")
            raw = stream.get("url")
            sha = fingerprint(raw)
            matching = next((u for u in uuids if (u, sha) in proof), None)
            append(uid=matching or (uuids[0] if uuids else None), go_id=go_id,
                   source="historical", identity="legacy_preserved",
                   raw_url=raw, codec=stream.get("codec"),
                   protocol=stream.get("protocol"))

    # All newly observed UUIDs are candidates; unknowns never hit an allowlist.
    for candidate in discovery["candidates"]:
        uid = checked_uuid(candidate["stationuuid"])
        result = by_uuid[uid]
        if result["classification"] == "already_mapped":
            # The historical streams above are the preserved baseline.
            # If Radio Browser offers a new URL, keep it as a separate review.
            classification = "mapped_directory_candidate"
        else:
            classification = result["classification"]
        append(uid=uid, go_id=result["existingGoStationId"],
               source="discovery", identity=classification,
               raw_url=candidate.get("streamUrl"),
               codec=candidate.get("codec"),
               duplicate_risk=bool(candidate.get("duplicateIdentityRisk")))
    queue.sort(key=lambda row: (row["priority"], row["goStationId"] or "",
                                row["stationuuid"] or "", row["streamSha256"] or ""))
    counts = {category: sum(row["transportLane"] == category for row in queue)
              for category in ("mp3_aac_first", "other_needs_format_check", "hls_deferred")}
    return {
        "schemaVersion": 1,
        "sourceScanDate": discovery.get("scanDate"),
        "historicalStationCount": len(catalog["stations"]),
        "preservedHistoricalStreamCount": sum(row["source"] == "historical" for row in queue),
        "discoveredCandidateCount": len(discovery["candidates"]),
        "queueCount": len(queue),
        "transportLaneCounts": counts,
        "admittedCount": 0,
        "deletedCount": 0,
        "technicalQualifiedCount": 0,
        "publicationAllowed": False,
        "requiresEditorialReview": True,
        "requiresDeviceBaselineForRelease": True,
        "items": queue,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--stream-evidence", type=Path)
    parser.add_argument("--legacy-ids", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing queue report")
    old_ids = set(load_json(args.legacy_ids)) if args.legacy_ids else None
    if old_ids is not None:
        old_ids = {checked_uuid(x) for x in old_ids}
    report = build_queue(load_json(args.catalog), load_json(args.discovery),
                         load_json(args.stream_evidence) if args.stream_evidence else None,
                         old_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("RADIO_QUALIFICATION_QUEUE_ONLY historical_streams="
          f"{report['preservedHistoricalStreamCount']} "
          f"candidates={report['discoveredCandidateCount']} "
          f"lanes={report['transportLaneCounts']} published=false")


if __name__ == "__main__":
    main()
