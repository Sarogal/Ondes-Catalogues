"""Offline independent gate for duplicate-only releases.

Recompute maintenance and repair evidence and conservative merge proposals.
Rebuild the expected catalogue without invoking the unified generator or
its merge mutation helper. No remote writes or external signing keys.
"""
import copy
from radio_daily_baseline_verify import strict_json
from radio_daily_lab_signing import validate_candidate
from radio_daily_maintenance_preview import build as maintenance_build
from radio_daily_repair_plan import plan as repair_plan
from radio_daily_merge_plan import plan as merge_plan, MAX_MERGES
from radio_daily_proposal_subset import select_proposals
from radio_daily_publication_simulator import publish
from radio_daily_v9_generator import digest, encode


def expected_merge_release(prior_body, *, expected_sha, expected_sequence, day,
                           maintenance, repair, confirmation, selected=None, fresh_check=None):
    sha = expected_sha
    if digest(prior_body) != sha:
        raise ValueError("merge baseline mismatch")
    if any(x.get("scanDate") != day for x in (maintenance, repair, confirmation)):
        raise ValueError("merge evidence date mismatch")
    checked = maintenance_build(prior_body, day, expected=sha, prior=maintenance)
    if any(checked[k] != maintenance.get(k) for k in ("records", "streams")):
        raise ValueError("maintenance evidence mismatch")
    repairs = repair_plan(prior_body, maintenance, repair, confirmation, expected=sha)
    old = strict_json(prior_body)
    proposals, _ = merge_plan(old, checked, day, {p["goStationId"] for p in repairs["proposals"]})
    if not proposals:
        raise ValueError("no qualified duplicate merge")
    if selected is not None:
        proposals = select_proposals(proposals, "sourceGoStationId", selected, MAX_MERGES)
    rows = {r["go_station_id"]: r for r in old["stations"]}
    expected = copy.deepcopy(old)
    removed = set()
    for p in proposals:
        sid, tid = p["sourceGoStationId"], p["targetGoStationId"]
        source, target = rows[sid], rows[tid]
        if (sid == tid or sid in removed or tid in removed
                or digest(encode(source)) != p["sourceSha256"]
                or digest(encode(target)) != p["targetSha256"]):
            raise ValueError("duplicate identity mismatch")
        if not {u["uuid"] for u in source["radio_browser_uuids"]} <= set(source["legacy_aliases"]):
            raise ValueError("historical UUID missing")
        if fresh_check is not None:
            fresh_check(p)
        removed.add(sid)
        expected["tombstones"].append(dict(go_station_id=sid,
            legacy_aliases=copy.deepcopy(source["legacy_aliases"]),
            retired_at=day+"T00:00:00Z", reason_code="merged_into_station",
            redirect_to=tid))
    expected["stations"] = [s for s in expected["stations"] if s["go_station_id"] not in removed]
    expected.update(release_sequence=expected_sequence+1,
                    generated_at=day+"T00:00:00Z")
    return encode(expected)


def validate_merge_release(prior_pointer, prior_body, candidate, *, anchor, day,
                           maintenance, repair, confirmation, selected=None, fresh_check=None):
    evidence = dict(maintenance=maintenance, repair=repair, confirmation=confirmation)
    if selected is not None:
        evidence["selected"] = selected
    if fresh_check is not None:
        evidence["fresh_check"] = fresh_check
    validate_candidate(prior_pointer, prior_body, candidate,
        expected_candidate_sha=digest(candidate), day=day, merge_evidence=evidence, **anchor)
    return digest(candidate)


def publish_merge_release(store, signer, prior_pointer, prior_body, candidate, *,
                          expected_sha, expected_sequence, expected_candidate_sha,
                          day, maintenance, repair, confirmation, checkpoint=None):
    anchor = dict(expected_sha=expected_sha, expected_sequence=expected_sequence,
                  public_key=signer.public_key, key_id=signer.key_id)
    verified = validate_merge_release(prior_pointer, prior_body, candidate,
        anchor=anchor, day=day, maintenance=maintenance, repair=repair,
        confirmation=confirmation)
    if verified != expected_candidate_sha:
        raise ValueError("validated candidate digest mismatch")
    return publish(store, signer, prior_pointer, prior_body, candidate,
        expected_sha=expected_sha, expected_sequence=expected_sequence,
        expected_candidate_sha=verified, day=day, checkpoint=checkpoint,
        merge_evidence=dict(maintenance=maintenance, repair=repair, confirmation=confirmation))
