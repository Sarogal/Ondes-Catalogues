"""Re-select the simulated visible release and migrate its full maintenance state.

This module reads the actual memory store, never a caller's claimed digest.
No state or experimental pointer is written to the real persistent branch.
"""
from radio_daily_release_context import prepare, STATE_FILES, MIGRATED_FILES, REQUALIFY
from radio_daily_v9_generator import digest


def migrate_visible(store, prior_pointer, prior_body, *, anchor, day, state, candidate_sha):
    if set(state) != set(STATE_FILES):
        raise ValueError("complete predecessor evidence required")
    current = store.current()
    def fetch(path, length):
        data = store.get(path)
        if len(data) != length:
            raise ValueError("visible catalogue length mismatch")
        return data
    raw, selection, files, context = prepare(current, fetch, day=day,
        state=state, prior_pointer=prior_pointer, prior_body=prior_body, **anchor)
    if (not selection["advanced"] or not context["signatureVerified"]
            or selection["selectedSequence"] != anchor["expected_sequence"]+1
            or digest(raw) != candidate_sha or set(files) != set(MIGRATED_FILES.values())
            or context["qualificationReportsToRebuild"] != list(REQUALIFY)):
        raise ValueError("incomplete successor migration")
    for report in files.values():
        if (report["catalogBaselineSha256"] != candidate_sha or report["scanDate"] != day
                or report["publicationAllowed"] is not False or report.get("approvedCount", 0) != 0):
            raise ValueError("invalid migrated report binding")
    if store.current() != current:
        raise ValueError("visible pointer changed during migration")
    # Prove the next selection can use the migrated state without a refetch
    # or a second version increment. The successor remains local to this run.
    new_anchor = dict(anchor, expected_sha=candidate_sha,
                      expected_sequence=selection["selectedSequence"])
    next_state = {key: files[name] for key, name in STATE_FILES.items()}
    def no_fetch(*args):
        raise ValueError("unchanged successor should reuse verified bytes")
    next_raw, next_selection, next_files, next_context = prepare(current, no_fetch,
        day=day, state=next_state, prior_pointer=current, prior_body=raw, **new_anchor)
    if (next_raw != raw or next_selection["advanced"] or next_files
            or next_context["stateMode"] != "unchanged" or store.current() != current):
        raise ValueError("migrated successor not reusable")
    return dict(migrationVerified=True, nextSelectionVerified=True,
        migratedFiles=sorted(files), qualificationReportsToRebuild=list(REQUALIFY),
        migration=context["migration"])
