"""Explicit first isolated publication: strict live admission, public bundle, Git transfer.

Only the reviewed workflow may invoke these modes. No production/TEST writes.
The first release adds qualified stations; other operation families stay in
the daily preview until the protected multiversion publisher is activated.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import tempfile
from pathlib import Path

from radio_daily_baseline_verify import PUBLIC_KEY, KEY_ID, verify_baseline, strict_json
from radio_daily_v9_generator import BASELINE, digest, encode, load_bytes
from radio_daily_decision_preview import decide
from radio_daily_proposal_subset import isolate
from radio_daily_admission_release_validation import (
    qualify_admission, validate_admission_release, MAX_ADMISSIONS, DIRECTORY_LIMIT)
from radio_daily_live_evidence import LiveEvidence
from radio_daily_combined_release_validation import compose, publish_combined
from radio_daily_protected_signer import load_signer
from radio_daily_live_inherited_artwork import recover_inherited
from radio_daily_publication_simulator import inventory
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_git_lab_transport import LocalGitLabTransport, REF, ZERO, snapshot
from radio_daily_github_transfer_contract import prepare, DESTINATION
from radio_daily_github_executor import transmit_github
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_github_readback import GitHubReadback, object_limit
from radio_daily_git_lab_reader import verify_snapshot_entries

TEST_ANCHOR = dict(expected_sha=BASELINE, expected_sequence=8,
                   public_key=PUBLIC_KEY, key_id=KEY_ID)


def pin():
    return dict(public_key=os.environ["RADIO_LAB_PUBLIC_KEY"],
                key_id=os.environ["RADIO_LAB_KEY_ID"])


def write_bundle(directory, files):
    directory.mkdir(exist_ok=False)
    for name, data in files.items():
        dest = directory/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("xb") as handle:
            handle.write(data)


def read_bundle(directory):
    files = {}
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink in public bundle")
        if path.is_dir():
            continue
        name = path.relative_to(directory).as_posix()
        if not 0 < path.stat().st_size <= object_limit(name):
            raise ValueError("unexpected public bundle file")
        files[name] = path.read_bytes()
    return files


def sign(args):
    # Remove signing credentials from subprocess environment immediately.
    encrypted = os.environ.pop("RADIO_LAB_ENCRYPTED_KEY")
    password = os.environ.pop("RADIO_LAB_PASSPHRASE").encode()
    pointer = load_bytes(args.pointer)
    raw = load_bytes(args.baseline)
    old = verify_baseline(pointer, raw, **TEST_ANCHOR)
    discovery = strict_json(load_bytes(args.reports/"candidates.json"))
    dossiers = strict_json(load_bytes(args.reports/"qualification-dossiers.json"))
    day = discovery["scanDate"]
    if day != dt.datetime.now(dt.timezone.utc).date().isoformat() or dossiers["scanDate"] != day:
        raise ValueError("fresh same-day collection required")
    ready = [r for r in decide(discovery, dossiers, BASELINE)["records"]
             if r["decision"] == "ready_for_staging_review"]
    result, material = isolate(pointer, raw, anchor=TEST_ANCHOR, day=day,
        proposed=ready, key="stationuuid", qualify=qualify_admission,
        validate=validate_admission_release, evidence=dict(discovery=discovery,dossiers=dossiers),
        live=LiveEvidence(directory_limit=DIRECTORY_LIMIT), maximum=MAX_ADMISSIONS)
    if material is None:
        raise ValueError("no independently qualified real admission; no release")
    operations = {"admission":material}
    candidate = compose(pointer, raw, anchor=TEST_ANCHOR, day=day,
                        operations=operations, objects={})
    inherited = recover_inherited(old, strict_json(candidate), cache_dirs=args.cache)
    signer = load_signer(encrypted, password, expected_public_key=pin()["public_key"],
                         expected_key_id=pin()["key_id"])
    lab_pointer = signer.reanchor_verified_baseline(pointer, raw, anchor=TEST_ANCHOR)
    with tempfile.TemporaryDirectory() as tmp:
        store = DurableLabStore.initialize(Path(tmp)/"catalog.sqlite", lab_pointer, raw,
            legacy_logos=inherited, **pin())
        publish_combined(store, signer, lab_pointer, raw, candidate,
            expected_sha=BASELINE, expected_sequence=8, expected_candidate_sha=digest(candidate),
            day=day, operations=operations, objects={})
        write_bundle(args.bundle, snapshot(store,9))
    print("RADIO_LAB_SIGNED_V9", digest(candidate), "admissions", result["selectedCount"])


def restore(directory, db):
    files = read_bundle(directory)
    # Verify every historical pointer, body and artwork before any Git writes.
    synthetic_commit = "1"*40
    selected = verify_snapshot_entries({p:len(b) for p,b in files.items()},
        files.__getitem__, lambda:synthetic_commit, expected_commit=synthetic_commit,
        bootstrap_sha=BASELINE, expected_sha=BASELINE, expected_sequence=8, **pin())
    if selected["sequence"] != 9:
        raise ValueError("first publication must be sequence 9")
    old = strict_json(selected["anchor_body"])
    legacy = {}
    for logo, name in inventory(old):
        if name is not None:
            raise ValueError("unexpected lab URL in immutable TEST bootstrap")
        path = "objects/sha256/"+logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]]
        legacy[logo["url"]] = files[path]
    store = DurableLabStore.initialize(db, selected["anchor_pointer"],
        selected["anchor_body"], legacy_logos=legacy, **pin())
    return files, selected, store


def stage_deterministic(source, store, sequence, parent):
    """Same public artifact always yields the same root/successor Git OIDs."""
    files = snapshot(store,sequence)
    staged = source._stage(files,parent)
    tree = source._git("rev-parse",staged+"^{tree}").decode().strip()
    day = strict_json(store.current())["published_at"][:10]
    env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="Radio Lab",GIT_AUTHOR_EMAIL="radio-lab@example.invalid",
        GIT_COMMITTER_NAME="Radio Lab",GIT_COMMITTER_EMAIL="radio-lab@example.invalid",
        GIT_AUTHOR_DATE=day+"T00:00:00Z",GIT_COMMITTER_DATE=day+"T00:00:00Z")
    cmd = ["git","--git-dir="+str(source.repository),"commit-tree",tree]
    if parent != ZERO:
        cmd += ["-p",parent]
    cmd += ["-m","Radio laboratory signed snapshot "+str(sequence)]
    commit = subprocess.run(cmd,env=env,check=True,capture_output=True,
                            timeout=30).stdout.decode().strip()
    source._verify_tree(commit,files)
    source._git("update-ref",REF,commit,parent)
    return commit


def transport(args):
    token = os.environ.pop("RADIO_LAB_JOB_TOKEN")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        files, selected, store = restore(args.bundle,root/"catalog.sqlite")
        bare = root/"source.git"
        subprocess.run(["git","init","--bare","--object-format=sha1",str(bare)],
                       check=True,capture_output=True,timeout=30)
        source = LocalGitLabTransport(bare)
        base = stage_deterministic(source,store,8,ZERO)
        # Construct exact successor before deciding whether a retry is needed.
        for name, data in files.items():
            if name.startswith(("releases/","objects/sha256/")):
                store.put_immutable(name,data)
        store.compare_and_swap(selected["anchor_pointer"],selected["pointer"])
        head = stage_deterministic(source,store,9,base)
        if snapshot(store,9) != files:
            raise ValueError("restored public bundle mismatch")
        reader = GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
        current = reader.read_head(DESTINATION,REF)
        if current not in (ZERO,base,head):
            raise ValueError("isolated ref already contains a different release")
        if current == ZERO:
            # A separate reconstructed sequence-8 store establishes the root.
            _, _, bootstrap = restore(args.bundle,root/"bootstrap.sqlite")
            source._git("update-ref",REF,base,head)
            plan = prepare(source,bootstrap,destination=DESTINATION,ref=REF,
                expected_commit=base,expected_remote_head=ZERO,expected_sequence=8,
                expected_sha=BASELINE)
            transmit_github(source,bootstrap,plan,read_head=reader.read_head,
                read_tree=reader.read_tree,write_token=token,authorized=True)
            source._git("update-ref",REF,head,base)
        reader = GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
        plan = prepare(source,store,destination=DESTINATION,ref=REF,
            expected_commit=head,expected_remote_head=base,expected_sequence=9,
            expected_sha=selected["sha256"])
        transmit_github(source,store,plan,read_head=reader.read_head,
            read_tree=reader.read_tree,write_token=token,authorized=True)
        args.receipt.write_bytes(encode(dict(commit=head,sequence=9,sha256=selected["sha256"])))
        print("RADIO_LAB_GIT_TRANSFERRED",head)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("sign","transport"))
    for name in ("pointer","baseline","reports","bundle","receipt"):
        p.add_argument("--"+name,type=Path)
    p.add_argument("--cache",type=Path,action="append")
    args=p.parse_args()
    if (os.environ.get("GITHUB_REPOSITORY") != "Sarogal/Ondes-Catalogues"
            or os.environ.get("GITHUB_REF") != "refs/heads/feature/radio-daily-discovery-lab-20261120"
            or os.environ.get("GITHUB_ACTIONS") != "true"):
        raise ValueError("reviewed isolated Actions context required")
    {"sign":sign,"transport":transport}[args.mode](args)


if __name__ == "__main__":
    main()
