"""Offline-lab repair release gate with explicit fresh evidence services.

Historical review is not authorization. Rehydrate official identity and
endpoint, then recheck audio continuity at the same endpoint. Only an exact
append-only fallback can be promoted. No key, CLI or network default.
"""
import copy
from urllib.parse import urlsplit
from radio_daily_baseline_verify import verify_baseline
from radio_daily_lab_signing import validate_candidate
from radio_daily_repair_plan import plan
from radio_daily_repair_material import recover
from radio_daily_v9_generator import digest, encode


def expected_repair_release(prior_pointer, prior_body, *, anchor, day, maintenance,
                   repair, confirmation, search, fetch, probe, continuity, hls):
    old = verify_baseline(prior_pointer, prior_body, **anchor)
    sha = anchor["expected_sha"]
    if any(x.get("scanDate") != day for x in (maintenance, repair, confirmation)):
        raise ValueError("repair evidence date mismatch")
    if any(not callable(x) for x in (search, fetch, probe, continuity, hls)):
        raise ValueError("explicit fresh evidence services required")
    report = plan(prior_body, maintenance, repair, confirmation, expected=sha)
    if not report["proposals"]:
        raise ValueError("no qualified repair proposal")
    urls, held = recover(prior_body, maintenance, repair, confirmation, report,
                         expected=sha, search=search, fetch=fetch)
    keys = {(p["goStationId"], p["streamSha256"]) for p in report["proposals"]}
    if held or set(urls) != keys:
        raise ValueError("fresh broadcaster material incomplete")
    expected = copy.deepcopy(old)
    rows = {r["go_station_id"]: r for r in expected["stations"]}
    for p in report["proposals"]:
        sid, fingerprint = p["goStationId"], p["streamSha256"]
        row = rows[sid]
        if (row["editorial"]["admission_state"] not in ("approved", "legacy_preserved")
                or row["status"].get("reason_code") == "synthetic_diagnostic_not_for_playback"
                or digest(encode(row)) != p["stationSha256"]):
            raise ValueError("station not eligible for strict repair")
        url = urls[(sid, fingerprint)]
        sample = probe(url)
        if sample.get("streamSha256") != fingerprint:
            raise ValueError("fresh probe fingerprint mismatch")
        if sample.get("verdict") == "audio_sample_ok" and sample.get("frameChain"):
            observation = continuity(url)
            codec = observation.get("frameCodec")
            if (observation.get("verdict") != "continuous_icy_frame_indication"
                    or codec != sample["frameChain"]):
                raise ValueError("fresh direct continuity required")
        elif sample.get("verdict") == "playlist_pending":
            observation = hls(url)
            codec = observation.get("frameCodec")
            if observation.get("verdict") != "advancing_hls_audio_frame_indication" or not codec:
                raise ValueError("fresh advancing HLS audio required")
        else:
            raise ValueError("fresh audio sample required")
        if not isinstance(codec, str) or not 0 < len(codec) <= 40:
            raise ValueError("invalid observed codec")
        row["streams"].append(dict(stream_id=p["streamId"], url=url,
            priority=p["priority"], protocol=urlsplit(url).scheme, state="verified",
            codec=codec, bitrate_kbps=None, last_checked_at=day+"T00:00:00Z",
            previous_urls=[]))
    expected.update(release_sequence=anchor["expected_sequence"]+1,
                    generated_at=day+"T00:00:00Z")
    return encode(expected)


def qualify_repair(prior_pointer, prior_body, *, anchor, day, **evidence):
    body = expected_repair_release(prior_pointer, prior_body, anchor=anchor,
                                   day=day, **evidence)
    validate_candidate(prior_pointer, prior_body, body,
        expected_candidate_sha=digest(body), day=day, repair_evidence=evidence, **anchor)
    return body


def validate_repair_release(prior_pointer, prior_body, candidate, *, anchor, day, **evidence):
    validate_candidate(prior_pointer, prior_body, candidate,
        expected_candidate_sha=digest(candidate), day=day, repair_evidence=evidence, **anchor)
    return digest(candidate)


def publish_repair_release(store, signer, prior_pointer, prior_body, candidate, *,
                           expected_sha, expected_sequence, expected_candidate_sha,
                           day, checkpoint=None, **evidence):
    from radio_daily_publication_simulator import publish
    return publish(store, signer, prior_pointer, prior_body, candidate,
        expected_sha=expected_sha, expected_sequence=expected_sequence,
        expected_candidate_sha=expected_candidate_sha, day=day,
        checkpoint=checkpoint, repair_evidence=evidence)
