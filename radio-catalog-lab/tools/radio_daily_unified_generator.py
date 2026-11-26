#!/usr/bin/env python3
"""Single unsigned catalogue preview; all inputs are pinned to the same v8.

Admission and repair engines remain evidence validators. No signing,
publication, network access, or mutation of the baseline occurs here.
"""
import argparse
import copy
from pathlib import Path

from radio_daily_v9_generator import BASELINE, build as add_build, digest, encode, check_catalog, load_bytes
from radio_daily_baseline_verify import strict_json, validate_shape, verify_baseline
from radio_daily_repair_plan import plan as repair_plan, simulate as repair_simulate
from radio_daily_status_preview import build as status_build, MAX_CHECKS
from radio_daily_logo_plan import plan as logo_plan, stage as logo_stage
from radio_daily_merge_plan import plan as merge_plan, apply as merge_apply, undo as merge_undo
from radio_daily_repair_material import live_recover
from radio_daily_logo_material import recover as recover_artwork


def stream_urls(station):
    return {u for v in station["streams"] for u in [v["url"], *v.get("previous_urls", [])]}


def build(raw, discovery, dossiers, decisions, maintenance, repair, confirmation,
          repair_report, status_report=None, logo_maintenance=None, missing_logo=None, *,
          urls=None, artwork=None, object_output=None, expected=BASELINE, expected_sequence=8):
    if object_output is not None and object_output:
        raise ValueError("fresh object output required")
    old = strict_json(raw)
    validate_shape(old)
    if digest(raw) != expected:
        raise ValueError("unified baseline mismatch")
    if type(expected_sequence) is not int or old["release_sequence"] != expected_sequence:
        raise ValueError("unified predecessor sequence mismatch")
    day = decisions["scanDate"]
    if any(x.get("scanDate") != day for x in (discovery, dossiers, maintenance, repair, confirmation, repair_report)):
        raise ValueError("unified evidence date mismatch")
    additions, admission = add_build(raw, discovery, dossiers, decisions, expected_sha=expected, expected_sequence=expected_sequence)
    checked = repair_plan(raw, maintenance, repair, confirmation, expected=expected)
    if checked != repair_report:
        raise ValueError("unified repair plan mismatch")
    proposed = {(p["goStationId"], p["streamSha256"]) for p in checked["proposals"]}
    supplied = dict(urls or {})
    if set(supplied) - proposed:
        raise ValueError("unexpected replacement material")
    pending = []
    repaired = None
    if proposed:
        if set(supplied) != proposed:
            pending = [{"goStationId": p["goStationId"], "streamSha256": p["streamSha256"],
                        "reason": "replacement_material_incomplete"} for p in checked["proposals"]]
        else:
            repaired = repair_simulate(raw, maintenance, repair, confirmation, checked, supplied, expected=expected)
    output = copy.deepcopy(repaired if repaired is not None else old)
    appended = strict_json(additions)["stations"][len(old["stations"]):] if additions else []
    repaired_urls = {u for s in output["stations"] for u in stream_urls(s)}
    added = []
    deferred = list(admission["deferred"])
    for s in sorted(appended, key=lambda x: x["go_station_id"]):
        uid = s["radio_browser_uuids"][0]["uuid"]
        if stream_urls(s) & repaired_urls:
            deferred.append({"stationuuid": uid, "reason": "conflict_with_existing_station_repair"})
            continue
        output["stations"].append(s)
        repaired_urls.update(stream_urls(s))
        added.append({"goStationId": s["go_station_id"], "stationuuid": uid})
    applied = checked["proposals"] if repaired is not None else []
    transitions, status_deferred = [], []
    original = {s["go_station_id"]: s for s in old["stations"]}
    current = {s["go_station_id"]: s for s in output["stations"]}
    if status_report is not None:
        if (status_report.get("scanDate") != day
                or type(status_report.get("attemptedCount")) is not int
                or not 0 <= status_report["attemptedCount"] <= MAX_CHECKS):
            raise ValueError("invalid status report date or budget")
        recomputed = status_build(raw, maintenance, checked, expected=expected, prior=status_report)
        # The recorded network budget differs from offline recomputation;
        # every decision, fingerprint and observation must still agree.
        recomputed["attemptedCount"] = status_report["attemptedCount"]
        if recomputed != status_report:
            raise ValueError("unified status report mismatch")
        repair_ids = {p["goStationId"] for p in checked["proposals"]}
        redirect_ids = {t.get("redirect_to") for t in old["tombstones"]}
        for p in sorted(recomputed["proposals"], key=lambda x: x["goStationId"]):
            sid = p["goStationId"]
            before = original[sid]
            station = current[sid]
            reason = None
            if before["status"].get("reason_code") == "synthetic_diagnostic_not_for_playback":
                reason = "synthetic_station_held"
            elif sid in repair_ids:
                reason = "repair_transition_conflict"
            elif p["to"] == "quarantined" and sid in redirect_ids:
                reason = "redirect_target_held"
            if reason:
                status_deferred.append({"goStationId": sid, "reason": reason})
                continue
            if digest(encode(before)) != p["stationSha256"] or station["status"]["state"] != p["from"]:
                raise ValueError("status station changed")
            previous_status = copy.deepcopy(station["status"])
            station["status"].update(state=p["to"],
                reason_code="experimental_recovery_review" if p["to"] == "active" else "experimental_unavailability_review",
                changed_at=day + "T00:00:00Z")
            transitions.append(dict(p, previousStatus=previous_status, proposedStatus=copy.deepcopy(station["status"])))
        if recomputed["massTransitionHeld"]:
            status_deferred.append({"reason": "mass_transition_held"})
    else:
        status_deferred.append({"reason": "status_report_not_supplied"})
    logo_changes, logo_deferred, objects = [], [], {}
    materials = dict(artwork or {})
    if (logo_maintenance is None)!=(missing_logo is None):
        raise ValueError("incomplete artwork reports")
    if logo_maintenance is not None:
        proposals, logo_deferred = logo_plan(raw,day,logo_maintenance,missing_logo,expected=expected)
        if set(materials)-{p["goStationId"] for p in proposals}:
            raise ValueError("unexpected artwork material")
        for p in proposals:
            sid=p["goStationId"]
            if sid not in materials:
                logo_deferred.append({"goStationId":sid,"operation":p["operation"],
                    "imageSha256":p["image"]["imageSha256"],"reason":"verified_object_and_identity_material_required"})
                continue
            descriptor,path,data=logo_stage(original[sid],p,materials[sid])
            if path in objects and objects[path]!=data:
                raise ValueError("artwork digest collision")
            objects[path]=data
            previous=copy.deepcopy(current[sid]["logo"])
            current[sid]["logo"]=descriptor
            logo_changes.append({"goStationId":sid,"operation":p["operation"],"previousLogo":previous,
                                 "proposedLogo":descriptor,"objectPath":path})
    elif materials:
        raise ValueError("artwork material without reports")
    else:
        logo_deferred.append({"reason":"artwork_reports_not_supplied"})
    blocked={p["goStationId"] for p in checked["proposals"]+transitions+logo_changes}
    merges, merge_deferred=merge_plan(old,maintenance,day,blocked)
    merge_apply(output,old,merges,day)
    changed = bool(added or applied or transitions or logo_changes or merges)
    report = {"schemaVersion": 1, "publicationAllowed": False, "signed": False,
              "catalogBaselineSha256": expected, "scanDate": day,
              "baselineSequence": old["release_sequence"], "candidateSequence": None,
              "candidateSha256": None, "changed": changed, "added": added,
              "repaired": applied, "admissionDeferred": deferred,
              "repairDeferred": checked["deferred"] + pending,
              "statusTransitions": transitions, "statusDeferred": status_deferred,
              "logoChanges": logo_changes, "logoDeferred": logo_deferred,
              "previewObjectPaths": sorted(objects),
              "merges": merges, "mergeDeferred": merge_deferred,
              "unsupportedOperations": [],
              "removed": [p["sourceGoStationId"] for p in merges],
              "existingStationsPreserved": len(old["stations"])-len(merges),
              "identitiesPreserved": len(old["stations"])+len(old["tombstones"]),
              "tombstonesPreserved": len(old["tombstones"])}
    if not changed:
        return None, report
    output["release_sequence"] = old["release_sequence"] + 1
    output["generated_at"] = day + "T00:00:00Z"
    # Reverse only authorized additions, fallback appends and status changes.
    restored = copy.deepcopy(output)
    merge_undo(restored,old,merges)
    restored["stations"] = restored["stations"][:len(old["stations"])]
    by_id = {s["go_station_id"]: s for s in restored["stations"]}
    for p in applied:
        last = by_id[p["goStationId"]]["streams"].pop()
        if last["stream_id"] != p["streamId"]:
            raise ValueError("unexpected repair delta")
    for p in transitions:
        station = by_id[p["goStationId"]]
        if station["status"] != p["proposedStatus"]:
            raise ValueError("unexpected status delta")
        station["status"] = p["previousStatus"]
    for p in logo_changes:
        station=by_id[p["goStationId"]]
        if station["logo"]!=p["proposedLogo"]:
            raise ValueError("unexpected artwork delta")
        station["logo"]=p["previousLogo"]
    for k in ("release_sequence", "generated_at"):
        restored[k] = old[k]
    if restored != old:
        raise ValueError("unified preservation failure")
    validate_shape(output)
    check_catalog(output, previous=old)
    payload = encode(output)
    report.update(candidateSequence=output["release_sequence"], candidateSha256=digest(payload))
    if object_output is not None:
        object_output.update(objects)
    return payload, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    names = ("pointer", "baseline", "discovery", "dossiers", "decisions", "maintenance",
             "repair", "confirmation", "repair-report", "status-report", "logo-maintenance", "missing-logo", "output-dir")
    for name in names:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--allow-repair-material-network", action="store_true")
    p.add_argument("--allow-logo-material-network", action="store_true")
    p.add_argument("--baseline-sha256",default=BASELINE)
    p.add_argument("--baseline-sequence",type=int,default=8)
    a = p.parse_args()
    if a.output_dir.exists():
        raise ValueError("fresh output directory required")
    raw = load_bytes(a.baseline)
    verify_baseline(load_bytes(a.pointer), raw, expected_sha=a.baseline_sha256, expected_sequence=a.baseline_sequence)
    evidence = [strict_json(load_bytes(getattr(a, k))) for k in
        ("discovery", "dossiers", "decisions", "maintenance", "repair", "confirmation", "repair_report", "status_report", "logo_maintenance", "missing_logo")]
    urls, held = ({}, [])
    if a.allow_repair_material_network:
        urls, held = live_recover(raw, *evidence[3:7],expected=a.baseline_sha256)
    artwork, artwork_held, objects = {}, [], {}
    if a.allow_logo_material_network:
        artwork, artwork_held = recover_artwork(raw,evidence[2]["scanDate"],*evidence[8:10],expected=a.baseline_sha256)
    payload, report = build(raw, *evidence, urls=urls, artwork=artwork, object_output=objects,expected=a.baseline_sha256,expected_sequence=a.baseline_sequence)
    report["logoMaterialDeferred"] = artwork_held
    report["logoMaterialRecoveredCount"] = len(artwork)
    report["repairMaterialDeferred"] = held
    report["repairMaterialRecoveredCount"] = len(urls)
    a.output_dir.mkdir(parents=True)
    if payload is not None:
        if objects:
            target=a.output_dir / "objects" / "sha256"
            target.mkdir(parents=True)
            for name,data in sorted(objects.items()):
                if digest(data)!=name.split(".")[0]:
                    raise ValueError("object output digest mismatch")
                with (target/name).open("xb") as f:
                    f.write(data)
        (a.output_dir / f"unsigned-candidate-v{report['candidateSequence']}.json").write_bytes(payload)
    (a.output_dir / "generation-report.json").write_bytes(encode(report))
    print("UNIFIED_UNSIGNED_CATALOG_PREVIEW", encode(report).decode())


if __name__ == "__main__":
    main()
