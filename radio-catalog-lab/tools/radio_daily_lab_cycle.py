"""Reusable, local-only publication and migration on one memory store.

All successors use the same ephemeral signer and store. No external storage,
network, signing key export or persistent registry mutation is supported.
"""
from radio_daily_baseline_verify import verify_baseline
from radio_daily_combined_release_validation import publish_combined, validate_combined
from radio_daily_live_state_migration import advance_visible
from radio_daily_publication_simulator import verify_visible
from radio_daily_v9_generator import digest


def publish_cycle(store, signer, pointer, raw, candidate, *, anchor, day,
                  operations, objects, state=None, checkpoint=None):
    if (anchor["public_key"], anchor["key_id"]) != (signer.public_key, signer.key_id):
        raise ValueError("experimental signer anchor mismatch")
    if store.current() != pointer:
        raise ValueError("cycle requires current predecessor")
    verify_baseline(pointer, raw, **anchor)
    sha = validate_combined(pointer, raw, candidate, anchor=anchor, day=day,
                            operations=operations, objects=objects)
    args = dict(expected_sha=anchor["expected_sha"],
                expected_sequence=anchor["expected_sequence"],
                expected_candidate_sha=sha, day=day,
                operations=operations, objects=objects)
    result = publish_combined(store, signer, pointer, raw, candidate,
                              checkpoint=checkpoint, **args)
    if candidate is None:
        if result["changed"] or result["sequence"] != anchor["expected_sequence"] or store.current()!=pointer:
            raise ValueError("unexpected unchanged cycle")
        return dict(changed=False, sequence=result["sequence"], publicationAllowed=False), state
    if not result["changed"] or result["sequence"] != anchor["expected_sequence"]+1:
        raise ValueError("unexpected simulated publication")
    current = store.current()
    verify_visible(store, current, sha=sha, sequence=result["sequence"], signer=signer)
    retry = publish_combined(store, signer, pointer, raw, candidate, **args)
    if not retry.get("resumed") or store.current() != current:
        raise ValueError("simulated retry not idempotent")
    return dict(changed=True, sequence=result["sequence"], publicationAllowed=False,
                retryVerified=True), None


def migrate_cycle(store, pointer, raw, candidate, *, anchor, day, state):
    return advance_visible(store, pointer, raw, anchor=anchor, day=day,
                           state=state, candidate_sha=digest(candidate))
