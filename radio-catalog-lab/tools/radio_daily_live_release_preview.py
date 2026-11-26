"""Recompute strict admission/repair/artwork evidence from live collectors; artifact only."""
import argparse
from pathlib import Path

from radio_daily_baseline_verify import verify_baseline, strict_json, KEY_ID, PUBLIC_KEY
from radio_daily_v9_generator import digest, encode, load_bytes
from radio_daily_decision_preview import decide
from radio_daily_repair_plan import plan
from radio_daily_repair_preview import PAGE_SIZE
from radio_daily_admission_release_validation import DIRECTORY_LIMIT, MAX_ADMISSIONS
from radio_daily_repair_confirmation import MAX_CHECKS
from radio_daily_proposal_subset import isolate
from radio_daily_admission_release_validation import qualify_admission, validate_admission_release
from radio_daily_repair_release_validation import qualify_repair, validate_repair_release
from radio_daily_live_evidence import LiveEvidence, EvidenceDeferred
from radio_daily_live_logo_preview import preview_logo
from radio_daily_live_maintenance_release_preview import preview_status, preview_merge
from radio_daily_live_combined_preview import combine_and_rehearse


def run(pointer, raw, *, anchor, day, discovery, dossiers, maintenance, repair, confirmation, logo_maintenance, missing_logo, status, cache_dirs=None):
    verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    if any(r.get("scanDate") != day for r in (discovery, dossiers, maintenance, repair, confirmation)):
        raise ValueError("live release input date mismatch")
    ready = [r for r in decide(discovery, dossiers, sha)["records"]
             if r["decision"] == "ready_for_staging_review"]
    repairs = plan(raw, maintenance, repair, confirmation, expected=sha)["proposals"]
    results = {}
    operations = {}
    for kind, proposed, qualify, validate, evidence in (
        ("admission", ready, qualify_admission, validate_admission_release,
         dict(discovery=discovery, dossiers=dossiers)),
        ("repair", repairs, qualify_repair, validate_repair_release,
         dict(maintenance=maintenance, repair=repair, confirmation=confirmation)),
    ):
        live = LiveEvidence(directory_limit=PAGE_SIZE if kind == "repair" else DIRECTORY_LIMIT)
        result, material = isolate(pointer, raw, anchor=anchor, day=day, proposed=proposed,
            key="goStationId" if kind == "repair" else "stationuuid", qualify=qualify,
            validate=validate, evidence=evidence, live=live,
            maximum=MAX_CHECKS if kind == "repair" else MAX_ADMISSIONS)
        if material is not None:
            operations[kind] = material
        results[kind] = result
    try:
        results["logo"] = preview_logo(pointer, raw, anchor=anchor, day=day,
            logo_maintenance=logo_maintenance, missing_logo=missing_logo, operations=operations)
    except ValueError:
        results["logo"] = dict(outcome="strict_gate_held", candidateSha256=None)
    for kind, operation, extra in (("status", preview_status, dict(status=status)),
                                  ("merge", preview_merge, {})):
        try:
            results[kind] = operation(pointer, raw, anchor=anchor, day=day,
                maintenance=maintenance, repair=repair, confirmation=confirmation, operations=operations, **extra)
        except ValueError:
            results[kind] = dict(outcome="strict_gate_held", candidateSha256=None)
    return dict(schemaVersion=1, scanDate=day, catalogBaselineSha256=sha,
                publicationAllowed=False, signed=False, operations=results,
                combined=combine_and_rehearse(pointer, raw, anchor=anchor, day=day, operations=operations, cache_dirs=cache_dirs,
                    state=dict(maintenance=maintenance, logo=logo_maintenance, missing=missing_logo,
                               status=status, repair=repair, confirmation=confirmation)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pointer", "baseline", "root"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, action="append")
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--baseline-sequence", type=int, required=True)
    args = parser.parse_args()
    def read(name):
        return strict_json(load_bytes(args.root / name))
    discovery = read("candidates.json")
    report = run(load_bytes(args.pointer), load_bytes(args.baseline),
        anchor=dict(expected_sha=args.baseline_sha256, expected_sequence=args.baseline_sequence,
                    public_key=PUBLIC_KEY, key_id=KEY_ID), day=discovery["scanDate"],
        discovery=discovery, dossiers=read("qualification-dossiers.json"),
        maintenance=read("maintenance-preview.json"), repair=read("repair-preview.json"),
        confirmation=read("repair-confirmation-preview.json"),
        logo_maintenance=read("logo-maintenance-preview.json"),
        missing_logo=read("missing-logo-preview.json"), status=read("status-transition-preview.json"),
        cache_dirs=args.cache_dir)
    with (args.root / "strict-live-release-preview.json").open("xb") as target:
        target.write(encode(report))
    print("STRICT_LIVE_RELEASE_PREVIEW", encode(report).decode())


if __name__ == "__main__":
    main()
