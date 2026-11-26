"""Build a narrow, unsigned laboratory recovery plan from activated history.

No generic rollback, key access, network, publication or pointer mutation.
Only restore a previously signed image for the same surviving station.
Retain every other current field and increase the logo revision.
"""
from radio_catalog_guard import validate_catalog
from radio_daily_baseline_verify import strict_json, validate_shape, verify_baseline
from radio_daily_publication_simulator import check_logo
from radio_daily_v9_generator import digest, encode
from radio_stream_recheck_ledger import parse_day


def plan_logo_recovery(store, *, expected_current_sha, historical_sequence, station_ids, day):
    day = parse_day(day)
    if (not isinstance(station_ids, (list, tuple)) or not station_ids
            or not all(isinstance(x, str) and x for x in station_ids)
            or len(set(station_ids)) != len(station_ids)):
        raise ValueError("explicit distinct recovery station IDs required")
    pointer = store.current()
    p = strict_json(pointer)
    if p["content_sha256"] != expected_current_sha:
        raise ValueError("current recovery anchor changed")
    if type(historical_sequence) is not int or not 8 <= historical_sequence < p["release_sequence"]:
        raise ValueError("strictly older activated sequence required")
    current_pointer, current_body = store.historical(p["release_sequence"])
    if current_pointer != pointer:
        raise ValueError("current recovery anchor changed")
    prior_pointer, prior_body = store.historical(historical_sequence)
    hp = strict_json(prior_pointer)
    anchor = dict(public_key=store.public_key, key_id=store.key_id)
    old = verify_baseline(prior_pointer, prior_body, expected_sha=hp["content_sha256"],
                          expected_sequence=historical_sequence, **anchor)
    current = verify_baseline(pointer, current_body, expected_sha=expected_current_sha,
                              expected_sequence=p["release_sequence"], **anchor)
    if day < current["generated_at"][:10]:
        raise ValueError("recovery date predates current release")
    result = strict_json(current_body)
    historic = {s["go_station_id"]: s for s in old["stations"]}
    present = {s["go_station_id"]: s for s in result["stations"]}
    for sid in sorted(station_ids):
        before, now = historic.get(sid), present.get(sid)
        if before is None or now is None:
            raise ValueError("recovery station missing from activated history")
        if not set(before["legacy_aliases"]).issubset(now["legacy_aliases"]):
            raise ValueError("recovery station identity mismatch")
        prior_logo, current_logo = before.get("logo"), now.get("logo")
        if prior_logo is None or current_logo is None:
            raise ValueError("recovery cannot add or remove a logo")
        if prior_logo["sha256"] == current_logo["sha256"]:
            raise ValueError("no logo content change to recover")
        check_logo(prior_logo, store.logo(prior_logo["url"]))
        now["logo"] = dict(prior_logo, revision=current_logo["revision"] + 1)
    result.update(release_sequence=p["release_sequence"] + 1, generated_at=day+"T00:00:00Z")
    validate_shape(result)
    issues = validate_catalog(result, mode="publish", previous=current,
                              authenticated_legacy=True, legacy_reference=result)
    if issues:
        raise ValueError("recovery contract refused: " + "; ".join(issues[:8]))
    if store.current() != pointer:
        raise ValueError("current recovery anchor changed")
    body = encode(result)
    return body, dict(schemaVersion=1, publicationAllowed=False, signed=False,
                      currentSha256=expected_current_sha, sourceSha256=hp["content_sha256"],
                      sourceSequence=historical_sequence, candidateSequence=result["release_sequence"],
                      candidateSha256=digest(body), stationIds=sorted(station_ids))
