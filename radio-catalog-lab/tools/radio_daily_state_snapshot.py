"""Build an isolated, complete successor state snapshot. No network or publication.

The caller supplies a trusted predecessor anchor (from the protected state
revision, NOT from the proposed current pointer). The returned directory can
be staged as one Git commit with a compare-and-swap on that state revision.
"""
import os
import tempfile
from pathlib import Path
from radio_daily_baseline_verify import strict_json
from radio_daily_release_context import prepare, STATE_FILES, MIGRATED_FILES, REQUALIFY
from radio_daily_v9_generator import encode, digest

POINTER = "release-anchor.json"
BODY = "release-baseline.json"
MAX_REPORT = 12 * 1024 * 1024
# Only independently reusable observations are copied. Decisions, candidate
# catalogues and derived classifications are intentionally not in this set.
RAW_OBSERVATIONS = ("ledger.json", "genre-hints.json", "stream-evidence.json",
                    "logo-preview.json", "editorial-preview.json", "continuity-preview.json",
                    "hls-preview.json", "metadata-preview.json",
                    "artist-research-preview.json", "recording-preview.json",
                    "wikidata-preview.json")


def bounded(path, limit):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("invalid state file: " + path.name)
    raw = path.read_bytes()
    if not 0 < len(raw) <= limit:
        raise ValueError("invalid state file size: " + path.name)
    return raw


def transition(previous_dir, output_dir, pointer, fetch_body, *, day, anchor):
    """Prepare a fresh atomic directory; never mutate the predecessor.

    A failed selection/migration must leave no successor directory. The
    output contains verified signed bytes and matching state together.
    """
    previous_dir, output_dir = Path(previous_dir), Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("fresh successor directory required")
    if not previous_dir.is_dir() or previous_dir.is_symlink():
        raise ValueError("invalid previous directory")
    prior_pointer = bounded(previous_dir / POINTER, 16384)
    prior_body = bounded(previous_dir / BODY, 10485760)
    reports = {key: strict_json(bounded(previous_dir / name, MAX_REPORT))
               for key, name in STATE_FILES.items() if (previous_dir / name).exists()}
    raw, selected, migrated, context = prepare(pointer, fetch_body, day=day,
        state=reports, prior_pointer=prior_pointer, prior_body=prior_body, **anchor)
    payloads = {POINTER: pointer, BODY: raw,
                "baseline-selection.json": encode(selected),
                "release-context.json": encode(context)}
    if selected["advanced"]:
        payloads.update({name: encode(report) for name, report in migrated.items()})
    else:
        payloads.update({STATE_FILES[key]: encode(report) for key, report in reports.items()})
        # The existing decisions remain valid for the same baseline only.
        for name in (*REQUALIFY, "repair-plan-preview.json", "programme-preview.json"):
            path = previous_dir / name
            if path.exists():
                data = strict_json(bounded(path, MAX_REPORT))
                if (data.get("schemaVersion") != 1 or data.get("publicationAllowed") is not False
                        or data.get("catalogBaselineSha256") != selected["selectedSha256"]):
                    # Some derived hints have no baseline binding. Rebuild them
                    # rather than silently treating them as authoritative.
                    continue
                payloads[name] = encode(data)
    for name in RAW_OBSERVATIONS:
        path = previous_dir / name
        if not path.exists():
            continue
        data = strict_json(bounded(path, MAX_REPORT))
        if data.get("schemaVersion") != 1 or data.get("publicationAllowed") is not False:
            raise ValueError("untrusted observation: " + name)
        binding = data.get("catalogBaselineSha256")
        if binding is not None and binding != selected["selectedSha256"]:
            continue
        # These remain observations; qualification must join them against the
        # newly reconciled discovery and catalogue before making decisions.
        payloads[name] = encode(data)
    # A same-filesystem directory rename exposes the complete snapshot at once.
    # This is local staging, not a concurrent remote publication protocol.
    with tempfile.TemporaryDirectory(prefix=".radio-state-", dir=output_dir.parent) as temp:
        stage = Path(temp) / "snapshot"
        stage.mkdir()
        for name, data in payloads.items():
            with (stage / name).open("xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        if digest((stage / BODY).read_bytes()) != selected["selectedSha256"]:
            raise ValueError("staged body changed")
        if output_dir.exists() or output_dir.is_symlink():
            raise ValueError("successor directory appeared concurrently")
        stage.rename(output_dir)
    return context
