"""Offline independent gate for status-only releases of existing stations.

Recompute repair and status proposals from evidence, never the generator's
report. Only existing stream availability transitions are in scope.
"""
import copy
from radio_daily_baseline_verify import strict_json
from radio_daily_lab_signing import validate_candidate
from radio_daily_repair_plan import plan
from radio_daily_status_preview import build as status_build, MAX_CHECKS, MAX_PROPOSALS, promote_recovery_stream
from radio_daily_proposal_subset import select_proposals
from radio_daily_publication_simulator import publish
from radio_daily_v9_generator import digest, encode


def expected_status_release(prior_body, *, expected_sha, expected_sequence, day,
                            maintenance, repair, confirmation, status, selected=None, fresh_check=None):
    sha = expected_sha
    if digest(prior_body) != sha:
        raise ValueError("status baseline mismatch")
    if any(x.get("scanDate") != day for x in (maintenance, repair, confirmation, status)):
        raise ValueError("status evidence date mismatch")
    repairs = plan(prior_body, maintenance, repair, confirmation, expected=sha)
    if type(status.get("attemptedCount")) is not int or not 0 <= status["attemptedCount"] <= MAX_CHECKS:
        raise ValueError("invalid status budget")
    checked = status_build(prior_body, maintenance, repairs, expected=sha, prior=status)
    checked["attemptedCount"] = status["attemptedCount"]
    if checked != status:
        raise ValueError("status evidence mismatch")
    expected = copy.deepcopy(strict_json(prior_body))
    rows = {r["go_station_id"]: r for r in expected["stations"]}
    repair_ids = {p["goStationId"] for p in repairs["proposals"]}
    redirect_ids = {t.get("redirect_to") for t in expected["tombstones"]}
    changed = 0
    records = {r["goStationId"]: r for r in checked["records"]}
    proposals = checked["proposals"]
    if selected is not None:
        proposals = select_proposals(proposals, "goStationId", selected, MAX_PROPOSALS)
    for proposal in proposals:
        sid = proposal["goStationId"]
        row = rows[sid]
        if (row["status"].get("reason_code") == "synthetic_diagnostic_not_for_playback"
                or sid in repair_ids
                or (proposal["to"] == "quarantined" and sid in redirect_ids)):
            continue
        if digest(encode(row)) != proposal["stationSha256"] or row["status"]["state"] != proposal["from"]:
            raise ValueError("status station identity mismatch")
        if fresh_check is not None:
            fresh_check(proposal)
        if proposal["to"] == "active":
            promote_recovery_stream(row, records[sid], day)
        row["status"].update(state=proposal["to"],
            reason_code="experimental_recovery_review" if proposal["to"] == "active"
                        else "experimental_unavailability_review",
            changed_at=day+"T00:00:00Z")
        changed += 1
    if not changed:
        raise ValueError("no qualified status transition")
    expected.update(release_sequence=expected_sequence+1,
                    generated_at=day+"T00:00:00Z")
    return encode(expected)


def validate_status_release(prior_pointer, prior_body, candidate, *, anchor, day,
                            maintenance, repair, confirmation, status, selected=None, fresh_check=None):
    evidence = dict(maintenance=maintenance, repair=repair,
                    confirmation=confirmation, status=status)
    if selected is not None:
        evidence["selected"] = selected
    if fresh_check is not None:
        evidence["fresh_check"] = fresh_check
    validate_candidate(prior_pointer, prior_body, candidate,
        expected_candidate_sha=digest(candidate), day=day, status_evidence=evidence, **anchor)
    return digest(candidate)


def publish_status_release(store, signer, prior_pointer, prior_body, candidate, *,
                           expected_sha, expected_sequence, expected_candidate_sha,
                           day, maintenance, repair, confirmation, status, checkpoint=None):
    anchor = dict(expected_sha=expected_sha, expected_sequence=expected_sequence,
                  public_key=signer.public_key, key_id=signer.key_id)
    verified = validate_status_release(prior_pointer, prior_body, candidate,
        anchor=anchor, day=day, maintenance=maintenance, repair=repair,
        confirmation=confirmation, status=status)
    if verified != expected_candidate_sha:
        raise ValueError("validated candidate digest mismatch")
    return publish(store, signer, prior_pointer, prior_body, candidate,
        expected_sha=expected_sha, expected_sequence=expected_sequence,
        expected_candidate_sha=verified, day=day, checkpoint=checkpoint,
        status_evidence=dict(maintenance=maintenance, repair=repair,
                             confirmation=confirmation, status=status))
