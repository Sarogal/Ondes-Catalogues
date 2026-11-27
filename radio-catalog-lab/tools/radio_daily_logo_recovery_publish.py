"""Execute explicitly selected logo recovery in the isolated local lab only."""
from radio_daily_baseline_verify import strict_json
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_logo_recovery_plan import build_logo_recovery
from radio_daily_publication_simulator import verify_visible
from radio_daily_v9_generator import digest


def publish_logo_recovery(store, signer, candidate, *, expected_current_sha,
                          expected_current_sequence, historical_sequence,
                          station_ids, day, checkpoint=None):
    """Rebuild exact bytes, retain history, switch once and verify on retry."""
    if not isinstance(store, DurableLabStore):
        raise ValueError("durable laboratory store required")
    if (store.public_key, store.key_id) != (signer.public_key, signer.key_id):
        raise ValueError("recovery signer identity mismatch")
    checkpoint = checkpoint or (lambda phase: None)
    prior, _ = store.historical(expected_current_sequence)
    rebuilt, report = build_logo_recovery(store, expected_current_sha=expected_current_sha,
        expected_current_sequence=expected_current_sequence,
        historical_sequence=historical_sequence, station_ids=station_ids, day=day)
    if candidate != rebuilt:
        raise ValueError("unauthorized recovery delta")
    sha = digest(rebuilt)
    sequence = expected_current_sequence + 1
    current = store.current()
    if current != prior:
        p = strict_json(current)
        if p["release_sequence"] != sequence or p["content_sha256"] != sha:
            raise ValueError("recovery concurrency conflict")
        verify_visible(store, current, sha=sha, sequence=sequence, signer=signer)
        if store.historical(sequence) != (current, rebuilt):
            raise ValueError("recovery history mismatch")
        return dict(report, signed=True, resumed=True)
    pointer = signer.sign_logo_recovery(store, rebuilt,
        expected_current_sha=expected_current_sha,
        expected_current_sequence=expected_current_sequence,
        historical_sequence=historical_sequence, station_ids=station_ids, day=day)
    checkpoint("signed")
    path = "releases/" + sha + ".json"
    store.put_immutable(path, rebuilt)
    checkpoint("catalogue_written")
    if store.get(path) != rebuilt:
        raise ValueError("recovery catalogue readback mismatch")
    checkpoint("before_pointer_swap")
    store.compare_and_swap(prior, pointer)
    checkpoint("after_pointer_swap")
    verify_visible(store, pointer, sha=sha, sequence=sequence, signer=signer)
    if store.historical(sequence) != (pointer, rebuilt):
        raise ValueError("recovery history mismatch")
    return dict(report, signed=True, resumed=False)
