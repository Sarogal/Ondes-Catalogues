"""Independent strict artwork preview using freshly fetched official material.

Only digests and safe reason codes leave the process. A failed station does not
discard other successfully recovered artwork. No signing or remote writes.
"""
from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_v9_generator import digest
from radio_daily_logo_plan import plan, stage
from radio_daily_logo_material import recover
from radio_daily_logo_release_validation import expected_logo_release, validate_logo_release
from radio_daily_live_evidence import LiveEvidence


def preview_logo(pointer, raw, *, anchor, day, logo_maintenance, missing_logo, operations=None):
    old = verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    proposals, _ = plan(raw, day, logo_maintenance, missing_logo, expected=sha)
    result = dict(proposalCount=len(proposals), networkCalls=0, candidateSha256=None,
                  outcome="no_proposal", recoveredCount=0, deferredCount=0,
                  objectCount=0, deferred=[])
    if not proposals:
        return result
    live = LiveEvidence()
    artwork, held = recover(raw, day, logo_maintenance, missing_logo, expected=sha,
                            fetch_page=live.fetch, fetch_image=live.image)
    result.update(networkCalls=live.calls, recoveredCount=len(artwork),
                  deferredCount=len(held), deferred=held)
    if not artwork:
        result["outcome"] = "live_evidence_deferred"
        return result
    rows = {r["go_station_id"]: r for r in old["stations"]}
    by_id = {p["goStationId"]: p for p in proposals}
    objects = {}
    for sid, material in artwork.items():
        _, path, data = stage(rows[sid], by_id[sid], material)
        if path in objects and objects[path] != data:
            raise ValueError("live artwork object collision")
        objects[path] = data
    evidence = dict(logo_maintenance=logo_maintenance, missing_logo=missing_logo,
                    artwork=artwork, objects=objects)
    candidate = expected_logo_release(raw, expected_sha=sha,
        expected_sequence=anchor["expected_sequence"], day=day, **evidence)
    verified = validate_logo_release(pointer, raw, candidate, anchor=anchor,
                                     day=day, **evidence)
    if verified != digest(candidate):
        raise ValueError("strict live logo digest mismatch")
    result.update(outcome="strict_gate_validated", candidateSha256=verified,
                  objectCount=len(objects))
    if operations is not None:
        operations["logo"] = dict(candidate=candidate, evidence=evidence)
    return result
