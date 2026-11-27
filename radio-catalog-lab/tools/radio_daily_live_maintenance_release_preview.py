"""Read-only fresh evidence checks for status and duplicate release proposals.

Historical reports remain necessary but are not enough for this live preview.
A failed fresh check holds its proposal; no publication occurs.
"""
from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import digest
from radio_daily_maintenance_preview import catalogue_rows
from radio_daily_repair_plan import plan as repair_plan
from radio_daily_status_preview import build as status_build, MAX_PROPOSALS, recovery_proof
from radio_daily_merge_plan import plan as merge_plan, MAX_MERGES
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


def select_live(pointer, raw, *, anchor, day, proposals, key, maximum,
                expected, validate, evidence, live, fresh_check, operations, kind):
    """Rebuild every trial from the complete reports, including fresh checks."""
    selected, candidate, verified, deferred = [], None, None, []
    for proposal in proposals:
        identifier = proposal[key]
        if len(selected) >= maximum:
            deferred.append(dict(id=identifier, reason="family_attempt_budget"))
            continue
        trial = sorted(selected + [identifier])
        args = dict(evidence, selected=trial, fresh_check=fresh_check)
        try:
            body = expected(raw, expected_sha=anchor["expected_sha"],
                expected_sequence=anchor["expected_sequence"], day=day, **args)
            sha = validate(pointer, raw, body, anchor=anchor, day=day, **args)
            if sha != digest(body):
                raise ValueError("strict digest mismatch")
        except EvidenceDeferred:
            deferred.append(dict(id=identifier, reason="live_evidence_deferred"))
            continue
        except ValueError:
            deferred.append(dict(id=identifier, reason="strict_gate_held"))
            continue
        selected, candidate, verified = trial, body, sha
    outcome = ("strict_gate_validated" if selected else "no_proposal" if not proposals
               else "live_evidence_deferred" if all(x["reason"]=="live_evidence_deferred" for x in deferred)
               else "strict_gate_held")
    if selected and operations is not None:
        operations[kind] = dict(candidate=candidate, evidence=dict(evidence,
            selected=selected, fresh_check=fresh_check))
    return dict(proposalCount=len(proposals), networkCalls=live.calls,
        candidateSha256=verified, outcome=outcome, selectedCount=len(selected),
        deferred=deferred)


def preview_status(pointer, raw, *, anchor, day, maintenance, repair, confirmation, status, operations=None):
    verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    repairs = repair_plan(raw, maintenance, repair, confirmation, expected=sha)
    checked = status_build(raw, maintenance, repairs, expected=sha, prior=status)
    checked["attemptedCount"] = status["attemptedCount"]
    if checked != status:
        raise ValueError("status evidence mismatch")
    _, streams = catalogue_rows(raw, sha)
    rows = {r['go_station_id']:r for r in verify_baseline(pointer, raw, **anchor)['stations']}
    records = {r["goStationId"]: r for r in checked["records"]}
    live = LiveEvidence()
    def fresh_check(proposal):
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
            p = recovery_proof(rows[sid], records[sid])
            url, fingerprint = streams[(sid, p["streamId"])]
            if fingerprint != p["streamSha256"]:
                raise ValueError("recovery fingerprint mismatch")
            if not positive(live, url, fingerprint):
                raise EvidenceDeferred("selected recovery stream not reconfirmed")
    return select_live(pointer, raw, anchor=anchor, day=day,
        proposals=checked["proposals"], key="goStationId", maximum=MAX_PROPOSALS,
        expected=expected_status_release, validate=validate_status_release,
        evidence=dict(maintenance=maintenance, repair=repair, confirmation=confirmation, status=status),
        live=live, fresh_check=fresh_check, operations=operations, kind="status")


def preview_merge(pointer, raw, *, anchor, day, maintenance, repair, confirmation, operations=None):
    old = verify_baseline(pointer, raw, **anchor)
    sha = anchor["expected_sha"]
    repairs = repair_plan(raw, maintenance, repair, confirmation, expected=sha)
    proposals, _ = merge_plan(old, maintenance, day, {p["goStationId"] for p in repairs["proposals"]})
    rows = {r["go_station_id"]: r for r in old["stations"]}
    live = LiveEvidence()
    def fresh_check(proposal):
        source = rows[proposal["sourceGoStationId"]]
        target = rows[proposal["targetGoStationId"]]
        urls = {digest(v["url"].encode()): v["url"] for v in source["streams"] if v in target["streams"]}
        for p in proposal["sharedEvidence"]:
            fingerprint = p["streamSha256"]
            url = urls[fingerprint]
            page = homepage_url(target["homepage"])
            if not page:
                continue
            try:
                mode, _, _ = confirm_page(target, page, url, live.fetch)
                if mode and positive(live, url, fingerprint):
                    return
            except EvidenceDeferred:
                continue
        raise EvidenceDeferred("shared broadcaster stream not reconfirmed")
    return select_live(pointer, raw, anchor=anchor, day=day,
        proposals=proposals, key="sourceGoStationId", maximum=MAX_MERGES,
        expected=expected_merge_release, validate=validate_merge_release,
        evidence=dict(maintenance=maintenance, repair=repair, confirmation=confirmation),
        live=live, fresh_check=fresh_check, operations=operations, kind="merge")
