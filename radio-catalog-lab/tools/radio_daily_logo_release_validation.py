"""Independent, fail-closed artwork-only release gate for the offline lab.

Never trusts a generator report. Recomputes the allowed delta from artwork
observations and exact source material. Other operation types are held until
their own independent gates exist. No network, private key or remote writes.
"""
import copy
from radio_daily_baseline_verify import strict_json
from radio_daily_lab_signing import validate_candidate
from radio_daily_logo_plan import plan, stage
from radio_daily_logo_maintenance import SOURCE_PREFIX, source_reference
from radio_daily_publication_simulator import publish
from radio_daily_v9_generator import digest, encode


def validate_logo_release(prior_pointer, prior_body, candidate, *, anchor, day,
                          logo_maintenance, missing_logo, artwork, objects):
    new = validate_candidate(prior_pointer, prior_body, candidate,
                             expected_candidate_sha=digest(candidate), day=day,
                             **anchor)
    old = strict_json(prior_body)
    proposals, _ = plan(prior_body, day, logo_maintenance, missing_logo,
                        expected=anchor["expected_sha"])
    allowed = {p["goStationId"]: p for p in proposals}
    if not artwork or set(artwork) - set(allowed):
        raise ValueError("unqualified artwork material")
    expected = copy.deepcopy(old)
    required = {}
    for row in expected["stations"]:
        sid = row["go_station_id"]
        if sid not in artwork:
            continue
        material = artwork[sid]
        descriptor, path, data = stage(row, allowed[sid], material)
        if path in required and required[path] != data:
            raise ValueError("artwork collision")
        required[path] = data
        row["logo"] = descriptor
        row["editorial"]["evidence_refs"] = [
            ref for ref in row["editorial"]["evidence_refs"]
            if not ref.startswith(SOURCE_PREFIX)
        ] + [source_reference(descriptor, material["sourceUrl"])]
    expected.update(release_sequence=anchor["expected_sequence"]+1,
                    generated_at=day+"T00:00:00Z")
    if new != expected or candidate != encode(expected):
        raise ValueError("unauthorized catalogue delta")
    if objects != required:
        raise ValueError("artwork inventory mismatch")
    return digest(candidate)


def publish_logo_release(store, signer, prior_pointer, prior_body, candidate, *,
                         expected_sha, expected_sequence, expected_candidate_sha,
                         day, logo_maintenance, missing_logo, artwork, objects,
                         checkpoint=None):
    anchor = dict(expected_sha=expected_sha, expected_sequence=expected_sequence,
                  public_key=signer.public_key, key_id=signer.key_id)
    verified = validate_logo_release(prior_pointer, prior_body, candidate,
        anchor=anchor, day=day, logo_maintenance=logo_maintenance,
        missing_logo=missing_logo, artwork=artwork, objects=objects)
    if verified != expected_candidate_sha:
        raise ValueError("validated candidate digest mismatch")
    return publish(store, signer, prior_pointer, prior_body, candidate,
        expected_sha=expected_sha, expected_sequence=expected_sequence,
        expected_candidate_sha=verified, day=day, objects=objects,
        checkpoint=checkpoint)
