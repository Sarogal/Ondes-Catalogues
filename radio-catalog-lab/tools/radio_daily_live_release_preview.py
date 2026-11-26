"""Recompute strict admission/repair evidence from live collectors; artifact only."""
import argparse
from pathlib import Path

from radio_daily_baseline_verify import verify_baseline, strict_json, KEY_ID, PUBLIC_KEY
from radio_daily_v9_generator import digest, encode, load_bytes
from radio_daily_decision_preview import decide
from radio_daily_repair_plan import plan
from radio_daily_repair_preview import PAGE_SIZE
from radio_daily_admission_release_validation import DIRECTORY_LIMIT
from radio_daily_admission_release_validation import qualify_admission, validate_admission_release
from radio_daily_repair_release_validation import qualify_repair, validate_repair_release
from radio_daily_live_evidence import LiveEvidence, EvidenceDeferred


def run(pointer, raw, *, anchor, day, discovery, dossiers, maintenance, repair, confirmation):
    verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    if any(r.get("scanDate") != day for r in (discovery, dossiers, maintenance, repair, confirmation)):
        raise ValueError("live release input date mismatch")
    ready = [r for r in decide(discovery, dossiers, sha)["records"]
             if r["decision"] == "ready_for_staging_review"]
    repairs = plan(raw, maintenance, repair, confirmation, expected=sha)["proposals"]
    results = {}
    for kind, proposed, qualify, validate, evidence in (
        ("admission", ready, qualify_admission, validate_admission_release,
         dict(discovery=discovery, dossiers=dossiers)),
        ("repair", repairs, qualify_repair, validate_repair_release,
         dict(maintenance=maintenance, repair=repair, confirmation=confirmation)),
    ):
        result = dict(proposalCount=len(proposed), networkCalls=0, candidateSha256=None,
                      outcome="no_proposal")
        if proposed:
            live = LiveEvidence(directory_limit=PAGE_SIZE if kind == "repair" else DIRECTORY_LIMIT)
            args = dict(anchor=anchor, day=day, **evidence, **live.services())
            try:
                candidate = qualify(pointer, raw, **args)
                verified = validate(pointer, raw, candidate, **args)
                if verified != digest(candidate):
                    raise ValueError("strict live candidate digest mismatch")
                result.update(outcome="strict_gate_validated", candidateSha256=verified)
            except EvidenceDeferred:
                result["outcome"] = "live_evidence_deferred"
            except ValueError:
                result["outcome"] = "strict_gate_held"
            result["networkCalls"] = live.calls
        results[kind] = result
    return dict(schemaVersion=1, scanDate=day, catalogBaselineSha256=sha,
                publicationAllowed=False, signed=False, operations=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pointer", "baseline", "root"):
        parser.add_argument("--"+name, type=Path, required=True)
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
        confirmation=read("repair-confirmation-preview.json"))
    with (args.root / "strict-live-release-preview.json").open("xb") as target:
        target.write(encode(report))
    print("STRICT_LIVE_RELEASE_PREVIEW", encode(report).decode())


if __name__ == "__main__":
    main()
