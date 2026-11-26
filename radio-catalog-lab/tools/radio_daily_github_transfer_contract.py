"""GitHub laboratory transfer contract; no default executor or credentials.

Only the dedicated experimental ref is permitted. The caller must supply
independent remote readback and an explicitly authorized command executor.
No CLI, workflow, token lookup or actual GitHub connection is enabled here.
"""
from dataclasses import dataclass

from radio_daily_baseline_verify import strict_json
from radio_daily_git_lab_transport import LocalGitLabTransport, OID, REF, ZERO, snapshot

DESTINATION = "https://github.com/Sarogal/Ondes-Catalogues.git"


@dataclass(frozen=True)
class TransferPlan:
    destination: str
    ref: str
    parent: str
    commit: str
    sequence: int
    catalogue_sha256: str

    def push_args(self):
        # A lease is an exact ref CAS, not permission for history replacement.
        # The plan is independently rebuilt before it is ever executed.
        lease = self.ref + ":" + ("" if self.parent == ZERO else self.parent)
        return ("-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
                "push", "--porcelain", "--atomic", "--no-follow-tags",
                "--force-with-lease="+lease, "--", self.destination,
                self.commit+":"+self.ref)


def prepare(source, store, *, destination, ref, expected_commit,
            expected_remote_head, expected_sequence, expected_sha):
    if destination != DESTINATION or ref != REF:
        raise ValueError("unauthorized GitHub laboratory destination")
    if not isinstance(source, LocalGitLabTransport):
        raise ValueError("verified local source required")
    if (not isinstance(expected_commit, str) or not OID.fullmatch(expected_commit)
            or expected_commit == ZERO or not isinstance(expected_remote_head, str)
            or not OID.fullmatch(expected_remote_head)):
        raise ValueError("explicit Git anchors required")
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
            raise ValueError("bootstrap requires exact sequence 8 root")
    else:
        if expected_sequence <= 8 or parents != [expected_commit, expected_remote_head]:
            raise ValueError("non-fast-forward or non-successor transfer refused")
        source._verify_tree(expected_remote_head, snapshot(store, expected_sequence-1))
    if source.head() != expected_commit or store.current() != pointer:
        raise ValueError("source anchor changed")
    return TransferPlan(destination, ref, expected_remote_head, expected_commit,
                        expected_sequence, expected_sha)


def transmit(source, store, plan, *, read_head, read_tree, execute,
             checkpoint=None):
    """Contract execution with injected adapters; no built-in network writes.

    read_head(destination, ref) returns exact ref SHA or ZERO for absence.
    read_tree(destination, commit) returns independently fetched public blobs
    of regular mode 100644, after rejecting symlinks, truncation and extra
    metadata. execute(tuple_of_git_args) must run trusted Git in the source
    bare repository with isolated configuration and scoped credentials.
    A failing transport may have committed, so always re-read the exact ref.
    """
    if type(plan) is not TransferPlan:
        raise ValueError("verified transfer plan required")
    if not all(callable(x) for x in (read_head, read_tree, execute)):
        raise ValueError("explicit remote adapters required")
    args = dict(destination=plan.destination, ref=plan.ref,
                expected_commit=plan.commit, expected_remote_head=plan.parent,
                expected_sequence=plan.sequence, expected_sha=plan.catalogue_sha256)
    if prepare(source, store, **args) != plan:
        raise ValueError("transfer plan changed")
    files = snapshot(store, plan.sequence)
    def head():
        result = read_head(plan.destination, plan.ref)
        if not isinstance(result, str) or not OID.fullmatch(result):
            raise ValueError("invalid remote ref response")
        return result
    def verify(commit, expected):
        if read_tree(plan.destination, commit) != expected:
            raise ValueError("remote tree readback mismatch")
    current = head()
    if current == plan.commit:
        verify(current, files)
        if head() != current:
            raise ValueError("remote concurrency conflict")
        return dict(commit=current, sequence=plan.sequence, resumed=True,
                    publicationAllowed=False, deploymentVerified=False)
    if current != plan.parent:
        raise ValueError("remote concurrency conflict")
    if current != ZERO:
        verify(current, snapshot(store, plan.sequence-1))
    checkpoint = checkpoint or (lambda phase: None)
    checkpoint("before_push")
    if prepare(source, store, **args) != plan or head() != plan.parent:
        raise ValueError("remote concurrency conflict before push")
    try:
        execute(plan.push_args())
    except (ValueError, OSError, RuntimeError):
        if head() != plan.commit:
            raise ValueError("remote lease rejected or transfer failed") from None
    checkpoint("after_push")
    if head() != plan.commit:
        raise ValueError("remote ref not at expected commit")
    verify(plan.commit, files)
    if head() != plan.commit:
        raise ValueError("remote concurrency conflict")
    return dict(commit=plan.commit, sequence=plan.sequence, resumed=False,
                publicationAllowed=False, deploymentVerified=False)
