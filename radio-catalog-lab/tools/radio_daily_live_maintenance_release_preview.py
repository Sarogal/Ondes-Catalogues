"""Read-only fresh evidence checks for status and duplicate release proposals.

Historical reports remain necessary but are not enough for this live preview.
A failed fresh check holds that family of operations; no publication occurs.
"""
from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import digest
from radio_daily_maintenance_preview import catalogue_rows
from radio_daily_repair_plan import plan as repair_plan
from radio_daily_status_preview import build as status_build
from radio_daily_merge_plan import plan as merge_plan
from radio_daily_status_release_validation import expected_status_release, validate_status_release
from radio_daily_merge_release_validation import expected_merge_release, validate_merge_release
from radio_daily_repair_confirmation import confirm_page
from radio_daily_editorial_preview import homepage_url
from radio_daily_live_evidence import LiveEvidence, EvidenceDeferred


def positive(live, url, sha):
    sample = live.probe(url)
    if sample.get("streamSha256") != sha:
        raise ValueError("fresh stream fingerprint mismatch")
    if sample.get("verdict") == "audio_sample_ok" and sample.get("frameChain"):
        result = live.continuity(url)
        return (result.get("verdict") == "continuous_icy_frame_indication"
                and result.get("frameCodec") == sample["frameChain"])
    if sample.get("verdict") == "playlist_pending":
        result = live.hls(url)
        return (result.get("verdict") == "advancing_hls_audio_frame_indication"
                and bool(result.get("frameCodec")))
    return False


def report_for(proposals):
    return dict(proposalCount=len(proposals), networkCalls=0,
                candidateSha256=None, outcome="no_proposal")


def preview_status(pointer, raw, *, anchor, day, maintenance, repair, confirmation, status):
    old = verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    repairs = repair_plan(raw, maintenance, repair, confirmation, expected=sha)
    checked = status_build(raw, maintenance, repairs, expected=sha, prior=status)
    checked["attemptedCount"] = status["attemptedCount"]
    if checked != status:
        raise ValueError("status evidence mismatch")
    proposals = checked["proposals"]
    result = report_for(proposals)
    if not proposals:
        return result
    args = dict(maintenance=maintenance, repair=repair, confirmation=confirmation, status=status)
    candidate = expected_status_release(raw, expected_sha=sha,
        expected_sequence=anchor["expected_sequence"], day=day, **args)
    _, streams = catalogue_rows(raw, sha)
    records = {r["goStationId"]: r for r in checked["records"]}
    live = LiveEvidence()
    try:
        for proposal in proposals:
            sid = proposal["goStationId"]
            proof = records[sid]["proof"]
            if not proof:
                raise ValueError("missing status proof")
            if proposal["to"] == "quarantined":
                if {p["streamId"] for p in proof} != {vid for s, vid in streams if s == sid}:
                    raise ValueError("incomplete variant proof")
                for p in proof:
                    url, fingerprint = streams[(sid, p["streamId"])]
                    if fingerprint != p["streamSha256"] or not live.unavailable(url):
                        raise EvidenceDeferred("unavailability not reconfirmed")
            else:
                recovered = False
                for p in proof:
                    url, fingerprint = streams[(sid, p["streamId"])]
                    if fingerprint != p["streamSha256"]:
                        raise ValueError("recovery fingerprint mismatch")
                    if positive(live, url, fingerprint):
                        recovered = True
                        break
                if not recovered:
                    raise EvidenceDeferred("recovery not reconfirmed")
        verified = validate_status_release(pointer, raw, candidate, anchor=anchor, day=day, **args)
        if verified != digest(candidate):
            raise ValueError("status digest mismatch")
        result.update(outcome="strict_gate_validated", candidateSha256=verified)
    except EvidenceDeferred:
        result["outcome"] = "live_evidence_deferred"
    result["networkCalls"] = live.calls
    return result


def preview_merge(pointer, raw, *, anchor, day, maintenance, repair, confirmation):
    old = verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    repairs = repair_plan(raw, maintenance, repair, confirmation, expected=sha)
    proposals, _ = merge_plan(old, maintenance, day, {p["goStationId"] for p in repairs["proposals"]})
    result = report_for(proposals)
    if not proposals:
        return result
    args = dict(maintenance=maintenance, repair=repair, confirmation=confirmation)
    candidate = expected_merge_release(raw, expected_sha=sha,
        expected_sequence=anchor["expected_sequence"], day=day, **args)
    rows = {r["go_station_id"]: r for r in old["stations"]}
    live = LiveEvidence()
    try:
        for proposal in proposals:
            source = rows[proposal["sourceGoStationId"]]
            target = rows[proposal["targetGoStationId"]]
            urls = {digest(v["url"].encode()): v["url"] for v in source["streams"] if v in target["streams"]}
            confirmed = False
            for p in proposal["sharedEvidence"]:
                fingerprint = p["streamSha256"]
                url = urls[fingerprint]
                page = homepage_url(target["homepage"])
                if not page:
                    continue
                mode, _, _ = confirm_page(target, page, url, live.fetch)
                if mode and positive(live, url, fingerprint):
                    confirmed = True
                    break
            if not confirmed:
                raise EvidenceDeferred("shared broadcaster stream not reconfirmed")
        verified = validate_merge_release(pointer, raw, candidate, anchor=anchor, day=day, **args)
        if verified != digest(candidate):
            raise ValueError("merge digest mismatch")
        result.update(outcome="strict_gate_validated", candidateSha256=verified)
    except EvidenceDeferred:
        result["outcome"] = "live_evidence_deferred"
    result["networkCalls"] = live.calls
    return result
