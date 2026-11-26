"""Read a verified public lab snapshot at an exact Git revision.

No network, secret key, production write or state mutation. The independently
retained key, bootstrap digest and last accepted catalogue anchor are mandatory.
"""
import base64
import re

from radio_daily_baseline_verify import PUBLIC_KEY, strict_json, verify_pointer
from radio_daily_baseline_selection import select
from radio_daily_git_lab_transport import LocalGitLabTransport, OID, ZERO
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_publication_simulator import check_logo, inventory
from radio_daily_release_context import prepare
from radio_daily_v9_generator import digest

SHA = re.compile(r"[a-f0-9]{64}")
HISTORY = re.compile(r"history/([1-9][0-9]*)\.json")
RELEASE = re.compile(r"releases/[a-f0-9]{64}\.json")
ARTWORK = re.compile(r"objects/sha256/[a-f0-9]{64}\.(?:png|jpg|webp)")


def read_snapshot(transport, *, expected_commit, bootstrap_sha, expected_sha,
                  expected_sequence, public_key, key_id):
    """Verify all activated history and select at most one new sequence."""
    if not isinstance(transport, LocalGitLabTransport):
        raise ValueError("local Git laboratory transport required")
    raw_key = base64.b64decode(public_key, validate=True)
    if (len(raw_key) != 32 or public_key == PUBLIC_KEY
            or key_id != "radio-lab-" + digest(raw_key)[:24]):
        raise ValueError("independent laboratory key required")
    if (not isinstance(expected_commit, str) or not OID.fullmatch(expected_commit)
            or expected_commit == ZERO or transport.head() != expected_commit):
        raise ValueError("Git head anchor mismatch")
    if (not isinstance(bootstrap_sha, str) or not SHA.fullmatch(bootstrap_sha)
            or not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha)
            or type(expected_sequence) is not int or expected_sequence < 8):
        raise ValueError("independent catalogue anchor required")
    entries = {}
    for row in transport._git("ls-tree", "-r", "-l", "-z", expected_commit).split(b"\0"):
        if not row:
            continue
        meta, path = row.split(b"\t", 1)
        mode, kind, oid, size = meta.decode("ascii").split()
        path = path.decode("ascii")
        limit = (16384 if path == "pointer.json" or HISTORY.fullmatch(path)
                 else 10485760 if RELEASE.fullmatch(path)
                 else 2097152 if ARTWORK.fullmatch(path) else 0)
        if (mode != "100644" or kind != "blob" or not OID.fullmatch(oid)
                or not 0 < int(size) <= limit or path in entries):
            raise ValueError("unexpected or oversized Git snapshot entry")
        entries[path] = (oid, int(size))
    needed = set()
    cache = {}
    def read(path, length=None):
        if path not in entries:
            raise ValueError("missing Git snapshot entry: " + path)
        oid, size = entries[path]
        if length is not None and size != length:
            raise ValueError("Git snapshot length mismatch")
        if path not in cache:
            data = transport._git("cat-file", "blob", oid)
            if len(data) != size:
                raise ValueError("Git snapshot readback length mismatch")
            cache[path] = data
        needed.add(path)
        return cache[path]
    pointer = read("pointer.json")
    p = strict_json(pointer)
    current_sequence = p.get("release_sequence")
    if type(current_sequence) is not int or current_sequence < expected_sequence:
        raise ValueError("catalogue rollback refused")
    if current_sequence > expected_sequence + 1:
        raise ValueError("missing intermediate state migration")
    # Bound work by the actual tree: a forged huge sequence cannot cause a loop.
    histories = [path for path in entries if HISTORY.fullmatch(path)]
    if len(histories) != current_sequence - 7:
        raise ValueError("incomplete Git release history")
    previous_pointer = previous_body = None
    previous_sha = bootstrap_sha
    anchored = False
    selected = None
    anchor_pointer = anchor_body = None
    for seq in range(8, current_sequence + 1):
        current = read("history/"+str(seq)+".json")
        cp = strict_json(current)
        if seq == 8:
            seq_anchor = dict(expected_sha=bootstrap_sha, expected_sequence=8)
        else:
            seq_anchor = dict(expected_sha=previous_sha, expected_sequence=seq-1)
        if cp.get("release_sequence") != seq:
            raise ValueError("history sequence mismatch")
        verify_pointer(current, expected_sha=cp["content_sha256"], expected_sequence=seq,
                       public_key=public_key, key_id=key_id)
        body, report = select(current, read, prior_pointer=previous_pointer,
            prior_body=previous_body, public_key=public_key, key_id=key_id, **seq_anchor)
        doc = strict_json(body)
        for logo, _ in inventory(doc):
            path = "objects/sha256/"+logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]]
            check_logo(logo, read(path, logo["byte_size"]))
        if seq == expected_sequence:
            if digest(body) != expected_sha:
                raise ValueError("catalogue anchor equivocation")
            anchored = True
            anchor_pointer, anchor_body = current, body
        previous_pointer, previous_body, previous_sha = current, body, digest(body)
        selected = report
    if not anchored or pointer != previous_pointer:
        raise ValueError("visible pointer differs from activated history")
    if set(entries) != needed:
        raise ValueError("unreferenced Git snapshot entry")
    if transport.head() != expected_commit:
        raise ValueError("Git head changed during verification")
    return dict(pointer=pointer, body=previous_body, anchor_pointer=anchor_pointer,
                anchor_body=anchor_body, commit=expected_commit,
                sequence=current_sequence, sha256=previous_sha)


def prepare_from_git(transport, *, day, state, **anchor):
    """Use existing migration contract; never trust a proposed state digest."""
    selected = read_snapshot(transport, **anchor)
    raw, report, migrated, context = prepare(selected["pointer"],
        lambda path, length: selected["body"], day=day, state=state,
        prior_pointer=selected["anchor_pointer"], prior_body=selected["anchor_body"],
        expected_sha=anchor["expected_sha"], expected_sequence=anchor["expected_sequence"],
        public_key=anchor["public_key"], key_id=anchor["key_id"])
    if transport.head() != selected["commit"]:
        raise ValueError("Git head changed during preparation")
    return raw, report, migrated, dict(context, gitCommit=selected["commit"])
