#!/usr/bin/env python3
"""Prepare legacy-preserved v5 TEST eligibility from three *independent* records.

The historical installed V64 inventory, the earlier 2026-11-15 admission
reconciliation, and an offline-verified TEST v4 predecessor together bind
the historical IDs to real short audio decode evidence. A failed station is
quarantined *without retirement, stream deletion, or forged human approval*.

Offline only; output cannot be signed or published by this tool.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from radio_catalog_guard import validate_catalog

BOOTSTRAP_BLOB = "fc1a465acfe7cb02ee9578cf5b83a27eba9e0723"
PREDECESSOR_GOIDS = {"go-station-900001", "go-station-900002",
                     "go-station-900010", "go-station-900011"}
KNOWN_HARDRADIO = {"HardRadio [MP3]", "HardRadio [AAC+]"}
CHECKED_AT = "2026-11-22T20:30:00Z"


def build_trusted_legacy(history: dict, coverage: dict, staging: dict) -> dict:
    if not isinstance(history, dict) or history.get("source", {}).get("blob_sha") != BOOTSTRAP_BLOB:
        raise ValueError("historical source is not the shipped V64 snapshot")
    rows = history.get("stations")
    if not isinstance(rows, list) or len(rows) != 310:
        raise ValueError("not the exact historical 310 station inventory")
    old = {}
    for row in rows:
        uuid = row["legacy_media_id"]
        if uuid in old:
            raise ValueError("duplicated historic UUID")
        old[uuid] = row["display_name"]

    known = coverage.get("new_station_rows")
    if coverage.get("source_v64_stations") != 310 or not isinstance(known, list) or len(known) != 9:
        raise ValueError("unrecognized previously-admitted 2026-11-15 UUID evidence")
    admitted = {}
    for row in known:
        if row.get("source") == "admission_uuid_evidence_20261115":
            if row.get("go_station_id") in admitted:
                raise ValueError("duplicate old admission identity")
            admitted[row["go_station_id"]] = row
    if len(admitted) != 7:
        raise ValueError("seven historically admitted but not shipped stations expected")

    if len(staging.get("stations", [])) != 320:
        raise ValueError("full 320-station reconciliation not supplied")
    trusted = {}
    for station in staging["stations"]:
        if station["editorial"]["admission_state"] != "legacy_preserved":
            continue
        goid = station["go_station_id"]
        historical = [
            (uuid, old[uuid]) for uuid in station["legacy_aliases"] if uuid in old
        ]
        if historical:
            uuid, old_name = sorted(historical)[0]
            if (station["display_name"].casefold() != old_name.casefold()
                and not (goid == "go-station-000146"
                         and station["display_name"] == "HardRadio"
                         and old_name in KNOWN_HARDRADIO)):
                raise ValueError("legacy UUID now maps to a different radio name")
            trusted[goid] = {
                "uuid": uuid, "name": old_name,
                "evidence_ref": f"v64-bootstrap:{BOOTSTRAP_BLOB}:{uuid}",
            }
        else:
            prior = admitted.get(goid)
            if not prior or prior["uuid"] not in station["legacy_aliases"] or \
                    prior["name"].casefold() != station["display_name"].casefold():
                raise ValueError("non-V64 station claims unsupported legacy admission")
            trusted[goid] = {
                "uuid": prior["uuid"], "name": prior["name"],
                "evidence_ref": f"prior-admission:20261115:{prior['uuid']}",
            }
    if len(trusted) != 316:
        raise ValueError(f"unexpected historic identity coverage: {len(trusted)}")
    return trusted


def prepare(catalog: dict, historical: dict, coverage: dict,
            audio_report: dict, signed_previous: dict):
    previous_stations = {s["go_station_id"]: s for s in signed_previous["stations"]}
    if signed_previous.get("release_sequence") != 4 or \
            set(previous_stations) != PREDECESSOR_GOIDS:
        raise ValueError("must use independently signed TEST generation 4")
    if catalog.get("release_sequence") != 5 or len(catalog.get("stations", [])) != 320:
        raise ValueError("unexpected TEST v5 draft inventory")
    if audio_report.get("streams_decoded_cumulative") != 345 or \
            audio_report.get("remaining_streams_not_decoded") != 13 or \
            not audio_report.get("stations_not_deleted") or \
            audio_report.get("no_signed_publication") is not True:
        raise ValueError("untrusted two-pass decoder verification")
    trusted = build_trusted_legacy(historical, coverage, catalog)
    absent = audio_report.get("active_without_decoded_stream")
    if not isinstance(absent, list) or len(absent) != 9:
        raise ValueError("expected nine failed real stations with explicit reasons")
    failed = {}
    for row in absent:
        id_ = row.get("go_station_id")
        if id_ in failed or not isinstance(row.get("reason_codes"), list) or not row["reason_codes"]:
            raise ValueError("unknown/duplicate/unanalyzed decoder failure")
        failed[id_] = row["reason_codes"]
    cloned = copy.deepcopy(catalog)
    before = {s["go_station_id"]: s for s in catalog["stations"]}
    for station in cloned["stations"]:
        goid = station["go_station_id"]
        if goid in previous_stations:
            # A previously signed stream may legitimately gain a *new* audio
            # verification timestamp. It may not lose a verified state, change
            # URLs/codec/priority, or rewrite its signed identity/logo/genre.
            prior = copy.deepcopy(previous_stations[goid])
            replayed = copy.deepcopy(station)
            old_stream_states = [s["state"] for s in prior["streams"]]
            new_stream_states = [s["state"] for s in replayed["streams"]]
            if any(a == "verified" and b != "verified"
                   for a, b in zip(old_stream_states, new_stream_states)):
                raise ValueError("signed TEST v4 stream verification regressed")
            for row in prior["streams"]:
                row.pop("state", None)
                row.pop("last_checked_at", None)
            for row in replayed["streams"]:
                row.pop("state", None)
                row.pop("last_checked_at", None)
            if replayed != prior:
                raise ValueError("signed TEST v4 identity, artwork or stream URL altered")
            continue
        if station["editorial"]["admission_state"] != "legacy_preserved" or goid not in trusted:
            raise ValueError("unexpected non-legacy addition")
        station["editorial"]["evidence_refs"].append(trusted[goid]["evidence_ref"])
        if goid in failed:
            if station["status"]["state"] != "active" or \
                    any(stream["state"] == "verified" for stream in station["streams"]):
                raise ValueError("falsely quarantining a verified radio")
            station["status"] = {
                "state": "quarantined",
                "reason_code": "two_pass_audio_probe_unavailable",
                "changed_at": CHECKED_AT
            }
            station["editorial"]["evidence_refs"].append(
                "audio-observation:20261122:358-streams-20-retries"
            )
        elif not any(stream["state"] == "verified" for stream in station["streams"]):
            raise ValueError("active admitted radio has no decoded audio")
    if len(failed) != 9 or len(cloned["stations"]) != len(before):
        raise ValueError("unexpected station removal/coverage")
    if sum(s["status"]["state"] == "active" for s in cloned["stations"]) != 309:
        raise ValueError("unexpected loss of playable stations")
    issues = validate_catalog(cloned, mode="publish", previous=signed_previous,
                              trusted_legacy=trusted, failed_audio_go_ids=set(failed))
    if issues:
        raise ValueError("publish admission gate refused: " + "; ".join(issues[:6]))
    # All old immutable stream URLs and aliases must survive qualification.
    for station in cloned["stations"]:
        old = before[station["go_station_id"]]
        if station["legacy_aliases"] != old["legacy_aliases"] or station["streams"] != old["streams"]:
            raise ValueError("destructive migration")
    report = {
        "scope": "UNSIGNED_LEGACY_EVIDENCE_BACKED_PUBLISH_PREFLIGHT",
        "original_stations": 320, "playable_active_stations": 309,
        "quarantined_stations": 11,
        "legacy_approved_by_machine_evidence": 316,
        "initially_verified_decoder_streams": 345,
        "failed_radio_go_ids": sorted(failed),
        "failed_audio_reasons_by_goid": failed,
        "legacy_provenance": trusted,
        "same_signed_test_v4_station_rows": 4,
        "publish_admission_guard_issues": issues,
        "publication_authorized": False,
        "signed_release_generated": False,
        "test_current_unchanged": True,
        "warning": "An admission-ready JSON is not a signed TEST v5 release; live logo byte hosting and key custody still pending.",
    }
    return cloned, report


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("catalog", "historical", "coverage", "audio-report", "previous",
              "out", "report"):
        p.add_argument("--"+k, required=True, type=Path)
    a=p.parse_args()
    if a.out.exists() or a.report.exists():
        p.error("refuse to overwrite existing unsigned results")
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    prepared, report = prepare(
        load(a.catalog), load(a.historical), load(a.coverage),
        load(a.audio_report), load(a.previous))
    a.out.write_text(json.dumps(prepared, ensure_ascii=False, indent=2)+"\n",
                     encoding="utf-8")
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({k:report[k] for k in (
        "original_stations", "playable_active_stations", "quarantined_stations",
        "legacy_approved_by_machine_evidence", "publish_admission_guard_issues",
        "signed_release_generated")}, sort_keys=True))


if __name__ == "__main__":
    main()
