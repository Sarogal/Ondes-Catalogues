"""Atomic Git transport rehearsal using a local bare repository only.

No network, GitHub token, workflow, production branch or real TEST key.
Export verified lab history, never a database or signing key. The dedicated
ref is a local stand-in for a future protected remote publisher branch.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_publication_simulator import check_logo, inventory
from radio_daily_v9_generator import digest

REF = "refs/heads/radio-lab-publisher-rehearsal"
ZERO = "0" * 40
OID = re.compile(r"[a-f0-9]{40}")


def snapshot(store, sequence):
    """Reverify activated history and export only public, content-addressed bytes."""
    if not isinstance(store, DurableLabStore) or type(sequence) is not int or sequence < 8:
        raise ValueError("verified laboratory history required")
    files = {}
    def put(path, data):
        if path in files and files[path] != data:
            raise ValueError("immutable snapshot collision")
        files[path] = data
    for seq in range(8, sequence + 1):
        pointer, body = store.historical(seq)
        p = strict_json(pointer)
        doc = verify_baseline(pointer, body, expected_sha=p["content_sha256"],
            expected_sequence=seq, public_key=store.public_key, key_id=store.key_id)
        put("history/"+str(seq)+".json", pointer)
        put(p["content_path"], body)
        for logo, _ in inventory(doc):
            data = store.logo(logo["url"])
            check_logo(logo, data)
            put("objects/sha256/"+logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]], data)
    files["pointer.json"] = pointer
    return files


class LocalGitLabTransport:
    def __init__(self, repository):
        self.repository = Path(repository).resolve(strict=True)
        if not self.repository.is_dir():
            raise ValueError("local bare Git directory required")
        if self._git("rev-parse", "--is-bare-repository") != b"true\n":
            raise ValueError("local bare Git repository required")
        if self._git("rev-parse", "--show-object-format") != b"sha1\n":
            raise ValueError("SHA-1 Git object format required for rehearsal")

    def _git(self, *args, data=None, index=None, allow_missing=False):
        env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Radio Lab", GIT_AUTHOR_EMAIL="radio-lab@example.invalid",
            GIT_COMMITTER_NAME="Radio Lab", GIT_COMMITTER_EMAIL="radio-lab@example.invalid")
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        proc = subprocess.run(["git", "--git-dir="+str(self.repository),
            "-c", "core.hooksPath="+os.devnull, *args], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        if allow_missing and proc.returncode == 1:
            return None
        if proc.returncode != 0:
            raise ValueError("local Git operation refused: " + args[0])
        return proc.stdout

    def head(self):
        raw = self._git("rev-parse", "--verify", "--quiet", REF, allow_missing=True)
        return ZERO if raw is None else raw.decode("ascii").strip()

    def _verify_tree(self, commit, files):
        if not OID.fullmatch(commit) or commit == ZERO:
            raise ValueError("invalid rehearsal commit")
        raw = self._git("ls-tree", "-r", "-z", commit)
        seen = {}
        for row in raw.split(b"\0"):
            if not row:
                continue
            metadata, path = row.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            path = path.decode("utf-8")
            if mode != "100644" or kind != "blob" or path not in files:
                raise ValueError("unexpected rehearsal tree entry")
            seen[path] = oid
        if set(seen) != set(files):
            raise ValueError("incomplete rehearsal tree")
        for path, oid in seen.items():
            if self._git("cat-file", "blob", oid) != files[path]:
                raise ValueError("rehearsal tree readback mismatch")

    def _stage(self, files, parent):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp)/"index"
            self._git("read-tree", "--empty", index=index)
            entries = []
            for path, data in sorted(files.items()):
                oid = self._git("hash-object", "-w", "--stdin", data=data).decode("ascii").strip()
                entries.append("100644 "+oid+"\t"+path+"\0")
            self._git("update-index", "-z", "--index-info",
                      data="".join(entries).encode(), index=index)
            tree = self._git("write-tree", index=index).decode("ascii").strip()
        args = ["commit-tree", tree]
        if parent != ZERO:
            args.extend(["-p", parent])
        args.extend(["-m", "Radio laboratory snapshot (not production)"])
        return self._git(*args).decode("ascii").strip()

    def publish(self, store, *, expected_head, expected_sequence, expected_sha, checkpoint=None):
        """One exact successor per transaction; retry verifies the committed tree."""
        checkpoint = checkpoint or (lambda phase: None)
        if not isinstance(expected_head, str) or not OID.fullmatch(expected_head):
            raise ValueError("explicit expected Git head required")
        pointer = store.current()
        p = strict_json(pointer)
        if p["release_sequence"] != expected_sequence or p["content_sha256"] != expected_sha:
            raise ValueError("local catalogue anchor mismatch")
        if expected_head == ZERO and expected_sequence != 8:
            raise ValueError("bootstrap must start at sequence 8")
        files = snapshot(store, expected_sequence)
        if expected_head != ZERO:
            if expected_sequence <= 8:
                raise ValueError("successor sequence required")
            previous = snapshot(store, expected_sequence-1)
            self._verify_tree(expected_head, previous)
        current = self.head()
        if current != expected_head:
            # Only the exact direct child with the expected public bytes is
            # an acceptable retry. A competing commit is never overwritten.
            parents = self._git("rev-list", "--parents", "-n", "1", current).decode().split() if current != ZERO else []
            wanted = [current] if expected_head == ZERO else [current, expected_head]
            if parents != wanted:
                raise ValueError("Git publication concurrency conflict")
            self._verify_tree(current, files)
            if self.head() != current or store.current() != pointer:
                raise ValueError("Git publication concurrency conflict")
            return dict(commit=current, sequence=expected_sequence, resumed=True,
                        publicationAllowed=False)
        if store.current() != pointer:
            raise ValueError("local catalogue anchor changed")
        commit = self._stage(files, expected_head)
        self._verify_tree(commit, files)
        checkpoint("before_ref_swap")
        if store.current() != pointer:
            raise ValueError("local catalogue anchor changed")
        try:
            self._git("update-ref", REF, commit, expected_head)
        except ValueError:
            raise ValueError("Git publication concurrency conflict") from None
        checkpoint("after_ref_swap")
        if self.head() != commit:
            raise ValueError("Git publication concurrency conflict")
        self._verify_tree(commit, files)
        return dict(commit=commit, sequence=expected_sequence, resumed=False,
                    publicationAllowed=False)
