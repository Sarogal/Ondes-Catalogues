"""Combine in-memory operation evidence and rehearse isolated signing.

No operation is admitted solely on a digest report. No signed pointer, key,
candidate bytes or raw network evidence is persisted by this module.
"""
from radio_daily_baseline_verify import verify_baseline
from radio_daily_combined_release_validation import compose, validate_combined
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_v9_generator import digest

# Prefer recovery/repair of existing radios to additions or destructive merges.
ORDER = ("repair", "status", "logo", "admission", "merge")


def inventory(operations):
    return operations.get("logo", {}).get("evidence", {}).get("objects", {})


def combine_and_rehearse(pointer, raw, *, anchor, day, operations):
    verify_baseline(pointer, raw, **anchor)
    if set(operations) - set(ORDER):
        raise ValueError("unknown live combined operation")
    selected = {}
    deferred = []
    body = None
    for kind in ORDER:
        if kind not in operations:
            continue
        trial = dict(selected, **{kind: operations[kind]})
        try:
            candidate = compose(pointer, raw, anchor=anchor, day=day,
                                operations=trial, objects=inventory(trial))
        except ValueError:
            deferred.append(dict(operation=kind, reason="combined_gate_held"))
            continue
        selected = trial
        body = candidate
    report = dict(publicationAllowed=False, signed=False, simulatedPublication=False,
                  experimentalSignatureVerified=False, candidateSha256=None,
                  candidateSequence=None, selectedOperations=list(selected),
                  deferredOperations=deferred,
                  outcome="no_change" if not operations else "combined_gate_held")
    if body is None:
        return report
    objects = inventory(selected)
    sha = digest(body)
    if validate_combined(pointer, raw, body, anchor=anchor, day=day,
                         operations=selected, objects=objects) != sha:
        raise ValueError("combined digest mismatch")
    report.update(candidateSha256=sha, candidateSequence=anchor["expected_sequence"]+1,
                  outcome="combined_unsigned_validated")
    # Only a transient key is created. Verify the original predecessor before
    # constructing an experimental trust chain with identical catalogue bytes.
    signer = EphemeralLabSigner()
    lab_pointer = signer.reanchor_verified_baseline(pointer, raw, anchor=anchor)
    lab_anchor = dict(expected_sha=anchor["expected_sha"],
                      expected_sequence=anchor["expected_sequence"],
                      public_key=signer.public_key, key_id=signer.key_id)
    try:
        # Rebuild against the new trust anchor and require identical bytes.
        if validate_combined(lab_pointer, raw, body, anchor=lab_anchor, day=day,
                             operations=selected, objects=objects) != sha:
            raise ValueError("laboratory reanchor digest mismatch")
        signed = signer.sign_candidate(lab_pointer, raw, body,
            expected_sha=anchor["expected_sha"], expected_sequence=anchor["expected_sequence"],
            expected_candidate_sha=sha, day=day,
            combined_evidence=dict(operations=selected, objects=objects))
        verify_baseline(signed, body, expected_sha=sha,
                        expected_sequence=anchor["expected_sequence"]+1,
                        public_key=signer.public_key, key_id=signer.key_id)
    except ValueError:
        report["outcome"] = "experimental_signing_held"
        return report
    report.update(outcome="experimental_signature_verified", signed=True,
                  experimentalSignatureVerified=True, experimentalKeyId=signer.key_id)
    return report
