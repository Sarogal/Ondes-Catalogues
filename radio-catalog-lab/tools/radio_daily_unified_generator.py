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


def stream_urls(station):
    return {u for v in station["streams"] for u in [v["url"], *v.get("previous_urls", [])]}


def build(raw, discovery, dossiers, decisions, maintenance, repair, confirmation,
          repair_report, status_report=None, *, urls=None, expected=BASELINE):
    old = strict_json(raw)
    validate_shape(old)
    if digest(raw) != expected:
        raise ValueError("unified baseline mismatch")
    day = decisions["scanDate"]
    if any(x.get("scanDate") != day for x in (discovery, dossiers, maintenance, repair, confirmation, repair_report)):
        raise ValueError("unified evidence date mismatch")
    additions, admission = add_build(raw, discovery, dossiers, decisions, expected_sha=expected)
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
    changed = bool(added or applied or transitions)
    report = {"schemaVersion": 1, "publicationAllowed": False, "signed": False,
              "catalogBaselineSha256": expected, "scanDate": day,
              "baselineSequence": old["release_sequence"], "candidateSequence": None,
              "candidateSha256": None, "changed": changed, "added": added,
              "repaired": applied, "admissionDeferred": deferred,
              "repairDeferred": checked["deferred"] + pending,
              "statusTransitions": transitions, "statusDeferred": status_deferred,
              "unsupportedOperations": ["logo_attachment", "logo_update", "merge_redirect"],
              "removed": [], "existingStationsPreserved": len(old["stations"]),
              "tombstonesPreserved": len(old["tombstones"])}
    if not changed:
        return None, report
    output["release_sequence"] = old["release_sequence"] + 1
    output["generated_at"] = day + "T00:00:00Z"
    # Reverse only authorized additions, fallback appends and status changes.
    restored = copy.deepcopy(output)
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
    for k in ("release_sequence", "generated_at"):
        restored[k] = old[k]
    if restored != old:
        raise ValueError("unified preservation failure")
    validate_shape(output)
    check_catalog(output, previous=old)
    payload = encode(output)
    report.update(candidateSequence=output["release_sequence"], candidateSha256=digest(payload))
    return payload, report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    names = ("pointer", "baseline", "discovery", "dossiers", "decisions", "maintenance",
             "repair", "confirmation", "repair-report", "status-report", "output-dir")
    for name in names:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        raise ValueError("fresh output directory required")
    raw = load_bytes(a.baseline)
    verify_baseline(load_bytes(a.pointer), raw)
    # Public runner has no transient repair URLs yet; pending repairs are
    # recorded rather than fetched or guessed. No competing v9 artifact.
    payload, report = build(raw, *(strict_json(load_bytes(getattr(a, k))) for k in
        ("discovery", "dossiers", "decisions", "maintenance", "repair", "confirmation", "repair_report", "status_report")))
    a.output_dir.mkdir(parents=True)
    if payload is not None:
        (a.output_dir / "unsigned-candidate-v9.json").write_bytes(payload)
    (a.output_dir / "generation-report.json").write_bytes(encode(report))
    print("UNIFIED_UNSIGNED_CATALOG_PREVIEW", encode(report).decode())


if __name__ == "__main__":
    main()
