#!/usr/bin/env python3
"""Build an unsigned, additive TEST v9 preview. Never sign or publish."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from radio_catalog_guard import validate_catalog, safe_url
from radio_catalog_daily_candidate_reconcile import review_candidates, checked_uuid
from radio_daily_decision_preview import decide

BASELINE = "f57e65f24f5ddd3a567907b28903fc309ea4c16747873b39f8d5a44348266f40"
MAX_BYTES = 25_000_000
GENRES = {"metal": "Metal", "heavy metal": "Heavy", "black metal": "Black",
          "death metal": "Death", "thrash metal": "Thrash", "trash metal": "Thrash",
          "doom metal": "Doom", "power metal": "Power", "folk metal": "Folk",
          "pagan metal": "Folk", "progressive metal": "Progressive",
          "symphonic metal": "Symphonic", "industrial metal": "Industrial",
          "metalcore": "Metalcore", "nu metal": "Metal", "hard rock": "Hard Rock",
          "punk": "Punk", "punk rock": "Punk", "punkrock": "Punk"}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def encode(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()

def load_bytes(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("oversized preview input")
    return path.read_bytes()

def check_catalog(doc, previous=None):
    issues = validate_catalog(doc, mode="staging", previous=previous)
    if issues:
        raise ValueError("catalogue guard refused: " + "; ".join(issues[:8]))

def build(baseline_bytes, discovery, dossiers, decisions, *, expected_sha=BASELINE, expected_sequence=8):
    if digest(baseline_bytes) != expected_sha:
        raise ValueError("baseline digest mismatch")
    baseline = json.loads(baseline_bytes)
    if (type(expected_sequence) is not int or expected_sequence < 8
            or baseline.get("release_sequence") != expected_sequence):
        raise ValueError(f"expected exact v{expected_sequence} predecessor")
    check_catalog(baseline)
    recomputed = decide(discovery, dossiers, expected_sha)
    if decisions != recomputed:
        raise ValueError("decision report does not match current evidence")
    reconciliation = review_candidates(baseline, discovery)
    classifications = {x["stationuuid"]: x["classification"] for x in reconciliation["candidates"]}
    sources = {checked_uuid(x["stationuuid"]): x for x in discovery["candidates"]}
    rows = {checked_uuid(x["stationuuid"]): x for x in dossiers["records"]}
    occupied = {x["go_station_id"] for x in baseline["stations"] + baseline["tombstones"]}
    aliases = {a for x in baseline["stations"] + baseline["tombstones"] for a in x["legacy_aliases"]}
    urls = {u for x in baseline["stations"] for s in x["streams"]
            for u in [s["url"], *s.get("previous_urls", [])]}
    output = copy.deepcopy(baseline)
    added, deferred = [], []
    day = decisions["scanDate"]
    timestamp = day + "T00:00:00Z"
    for row in recomputed["records"]:
        if row["decision"] != "ready_for_staging_review":
            continue
        uid = checked_uuid(row["stationuuid"])
        source, evidence = sources[uid], rows[uid]
        stream = source.get("streamUrl")
        page = source.get("homepage")
        if (classifications.get(uid) != "unmapped_candidate" or uid in aliases
                or stream in urls or not safe_url(stream) or not safe_url(page)):
            deferred.append({"stationuuid": uid, "reason": "identity_or_url_recheck"})
            continue
        # Keep the existing numeric GO ID contract. Stable across input ordering;
        # any collision is a hard refusal, never a reassignment of an old ID.
        goid = "go-station-" + str(10**14 + int(digest(uid.encode())[:14], 16) % (9*10**14))
        if goid in occupied:
            raise ValueError("stable GO ID collision")
        terms = evidence["homepageEvidence"]["programmeScopeTerms"]
        genres = sorted({GENRES[t.lower()] for t in terms if t.lower() in GENRES})
        if not genres:
            deferred.append({"stationuuid": uid, "reason": "genre_mapping_required"})
            continue
        country = source.get("countrycode") or None
        if country and not re.fullmatch("[A-Z]{2}", country):
            country = None
        if not isinstance(source.get("name"), str) or not 0 < len(source["name"].strip()) <= 180:
            deferred.append({"stationuuid": uid, "reason": "name_contract_recheck"})
            continue
        station = {
            "go_station_id": goid, "display_name": source["name"].strip(),
            "country_code": country, "genres": genres, "homepage": page,
            "radio_browser_uuids": [{"uuid": uid, "state": "current"}],
            "legacy_aliases": [uid],
            "status": {"state": "active", "reason_code": "experimental_staging_only",
                       "changed_at": timestamp},
            "streams": [{"stream_id": "discovered-stream-001", "url": stream,
                         "priority": 0, "protocol": urlsplit(stream).scheme,
                         "codec": None, "bitrate_kbps": None, "state": "candidate_verified",
                         "last_checked_at": None, "previous_urls": []}],
            # Decoded previews are NOT verified logo identity or durable objects.
            "logo": None,
            "editorial": {"admission_state": "approved", "reviewed_at": timestamp,
                          "evidence_refs": ["experimental-decision:" + digest(encode(row)),
                                            "experimental-dossier:" + digest(encode(evidence))]},
        }
        output["stations"].append(station)
        occupied.add(goid)
        aliases.add(uid)
        urls.add(stream)
        added.append({"stationuuid": uid, "go_station_id": goid, "logo": "deferred_unverified"})
    report = {"schemaVersion": 1, "publicationAllowed": False, "signed": False,
              "baselineSha256": expected_sha, "baselineSequence": expected_sequence,
              "decisionSha256": digest(encode(decisions)), "scanDate": day,
              "stagingReviewCount": recomputed["stagingReviewCount"],
              "added": added, "deferred": deferred, "modified": [], "removed": [],
              "decisionCounts": recomputed["counts"],
              "existingStationsPreserved": len(baseline["stations"]),
              "tombstonesPreserved": len(baseline["tombstones"]),
              "candidateSequence": expected_sequence + 1 if added else None,
              "candidateSha256": None, "changed": bool(added)}
    if not added:
        return None, report
    output["release_sequence"] = expected_sequence + 1
    output["generated_at"] = timestamp
    if (output["stations"][:len(baseline["stations"])] != baseline["stations"]
            or output["tombstones"] != baseline["tombstones"]):
        raise ValueError("baseline preservation failure")
    check_catalog(output, previous=baseline)
    payload = encode(output)
    report["candidateSha256"] = digest(payload)
    return payload, report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "discovery", "dossiers", "decisions", "output-dir"):
        p.add_argument("--"+name, type=Path, required=True)
    a = p.parse_args()
    # A fresh directory prevents a stale v9 file surviving a no-change run.
    if a.output_dir.exists():
        raise ValueError("output directory must not already exist")
    payload, report = build(load_bytes(a.baseline), json.loads(load_bytes(a.discovery)),
                            json.loads(load_bytes(a.dossiers)), json.loads(load_bytes(a.decisions)))
    a.output_dir.mkdir(parents=True)
    if payload is not None:
        (a.output_dir/"unsigned-candidate-v9.json").write_bytes(payload)
    (a.output_dir/"generation-report.json").write_bytes(encode(report))
    print("UNSIGNED_V9_PREVIEW", json.dumps(report, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    main()
