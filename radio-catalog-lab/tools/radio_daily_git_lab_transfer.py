"""Remote Git protocol rehearsal, strictly between two local bare repositories.

There is no network destination, credential reader, production ref or CLI.
The source is a verified laboratory commit. Only its exact direct successor
may be pushed, using a lease on the dedicated receiver ref.
"""
from radio_daily_baseline_verify import strict_json
from radio_daily_git_lab_transport import LocalGitLabTransport, OID, REF, ZERO, snapshot


def transmit(source, receiver, store, *, expected_commit, expected_remote_head,
             expected_sequence, expected_sha, checkpoint=None):
    """Transfer one activated lab snapshot; verify remote bytes and retry safely."""
    if not isinstance(source, LocalGitLabTransport) or not isinstance(receiver, LocalGitLabTransport):
        raise ValueError("two local laboratory repositories required")
    if source.repository == receiver.repository:
        raise ValueError("distinct local laboratory repositories required")
    if not isinstance(expected_commit, str) or not OID.fullmatch(expected_commit) or expected_commit == ZERO:
        raise ValueError("explicit source commit required")
    if not isinstance(expected_remote_head, str) or not OID.fullmatch(expected_remote_head):
        raise ValueError("explicit remote lease required")
    if source.head() != expected_commit:
        raise ValueError("source Git anchor mismatch")
    pointer = store.current()
    p = strict_json(pointer)
    if (type(expected_sequence) is not int or p["release_sequence"] != expected_sequence
            or p["content_sha256"] != expected_sha):
        raise ValueError("local catalogue anchor mismatch")
    files = snapshot(store, expected_sequence)
    source._verify_tree(expected_commit, files)
    parents = source._git("rev-list", "--parents", "-n", "1", expected_commit).decode().split()
    if expected_remote_head == ZERO:
        if expected_sequence != 8 or parents != [expected_commit]:
            raise ValueError("remote bootstrap requires exact root sequence 8")
    else:
        if expected_sequence <= 8 or parents != [expected_commit, expected_remote_head]:
            raise ValueError("remote successor must be a direct child of lease")
        source._verify_tree(expected_remote_head, snapshot(store, expected_sequence-1))
    current = receiver.head()
    if current == expected_commit:
        receiver._verify_tree(current, files)
        if receiver.head() != current or source.head() != expected_commit or store.current() != pointer:
            raise ValueError("remote Git concurrency conflict")
        return dict(commit=current, sequence=expected_sequence, resumed=True,
                    publicationAllowed=False)
    if current != expected_remote_head:
        raise ValueError("remote Git concurrency conflict")
    if current != ZERO:
        receiver._verify_tree(current, snapshot(store, expected_sequence-1))
    checkpoint = checkpoint or (lambda phase: None)
    checkpoint("before_push")
    if source.head() != expected_commit or store.current() != pointer:
        raise ValueError("source Git anchor changed")
    # An explicit empty lease means the destination must not yet exist.
    # Force-with-lease is used solely for CAS; ancestry was checked above.
    lease = REF + ":" + ("" if expected_remote_head == ZERO else expected_remote_head)
    try:
        source._git("-c", "protocol.allow=never", "-c", "protocol.file.allow=always",
            "push", "--porcelain", "--atomic", "--no-follow-tags", "--no-verify",
            "--force-with-lease="+lease, "--", str(receiver.repository),
            expected_commit+":"+REF)
    except ValueError:
        # A lost acknowledgement may conceal an already completed transfer.
        if receiver.head() != expected_commit:
            raise ValueError("remote Git lease rejected or transfer failed") from None
    checkpoint("after_push")
    if receiver.head() != expected_commit:
        raise ValueError("remote Git concurrency conflict")
    receiver._verify_tree(expected_commit, files)
    if receiver.head() != expected_commit:
        raise ValueError("remote Git concurrency conflict")
    return dict(commit=expected_commit, sequence=expected_sequence, resumed=False,
                publicationAllowed=False)
