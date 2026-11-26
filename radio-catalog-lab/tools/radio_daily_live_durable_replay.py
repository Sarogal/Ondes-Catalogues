"""Replay the exact verified live-preview release in disposable durable Git storage.

No new network observations, no new signing, no actual deployment, no remote
write and no durable successor on GitHub. Only a digest-only report escapes.
"""
import subprocess
import tempfile
from pathlib import Path

from radio_daily_baseline_verify import strict_json
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_git_lab_transport import LocalGitLabTransport, ZERO
from radio_daily_git_lab_transfer import transmit
from radio_daily_git_lab_reader import prepare_from_git
from radio_daily_deployment_verify import verify_deployment, PublicResponse, ROOT, POINTER_URL
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_publication_simulator import inventory, verify_visible
from radio_daily_v9_generator import digest


def rehearse(store, signer, prior, raw, body, *, anchor, day, state, inherited, objects):
    """Replay a previously validated in-memory publication, never export its key."""
    if anchor["expected_sequence"] != 8:
        raise ValueError("live durable rehearsal requires v8 bootstrap")
    key = dict(public_key=signer.public_key, key_id=signer.key_id)
    pointer = store.current()
    sha = digest(body)
    verify_visible(store, pointer, sha=sha, sequence=9, signer=signer)
    if store.get("releases/"+sha+".json") != body:
        raise ValueError("live rehearsal candidate bytes changed")
    old = strict_json(raw)
    legacy = {logo["url"]: inherited[logo["url"]] for logo, name in inventory(old)
              if name is None}
    if any(name is not None for _, name in inventory(old)):
        raise ValueError("live rehearsal bootstrap contains laboratory artwork")
    with tempfile.TemporaryDirectory(prefix="radio-live-lab-") as tmp:
        root = Path(tmp).resolve()
        db = root/"catalog.sqlite"
        durable = DurableLabStore.initialize(db, prior, raw, legacy_logos=legacy, **key)
        def repo(name):
            path = root/name
            subprocess.run(["git","init","--bare","--object-format=sha1",str(path)],
                           check=True, capture_output=True, timeout=30)
            return LocalGitLabTransport(path)
        source, receiver = repo("source.git"), repo("receiver.git")
        def transfer(seq, content_sha, lease):
            head = source.publish(durable, expected_head=lease,
                expected_sequence=seq, expected_sha=content_sha)["commit"]
            args = dict(expected_commit=head, expected_remote_head=lease,
                        expected_sequence=seq, expected_sha=content_sha)
            transmit(source, receiver, durable, **args)
            if not transmit(source, receiver, durable, **args)["resumed"]:
                raise ValueError("live durable transfer retry mismatch")
            return head
        base = transfer(8, digest(raw), ZERO)
        for name, data in objects.items():
            durable.put_immutable("objects/sha256/"+name, data)
        durable.put_immutable("releases/"+sha+".json", body)
        # The exact already verified signature is reused. Simulate process
        # restart after staging, then activate atomically in the local database.
        durable = DurableLabStore(db, **key)
        durable.compare_and_swap(prior, pointer)
        durable = DurableLabStore(db, **key)
        verify_visible(durable, pointer, sha=sha, sequence=9, signer=signer)
        head = transfer(9, sha, base)
        paths = {POINTER_URL: ("pointer.json","application/json"),
                 ROOT+"releases/"+sha+".json": ("releases/"+sha+".json","application/json")}
        for logo, _ in inventory(strict_json(body)):
            paths[logo["url"]] = ("objects/sha256/"+logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]],
                                  logo["mime_type"])
        def read(url, limit):
            path, mime = paths[url]
            data = receiver._git("show", head+":"+path)
            if len(data) > limit:
                raise ValueError("local simulated public read exceeds limit")
            return PublicResponse(200, url, mime, data)
        args = dict(expected_commit=head, bootstrap_sha=digest(raw), **anchor)
        accepted = verify_deployment(receiver, deployment_commit=head,
            deployment_status="success", fetch=read, **args)
        selected, _, migrated, context = prepare_from_git(receiver, day=day,
            state=state, **args)
        if selected != body or not migrated or context["selectedSequence"] != 9:
            raise ValueError("live durable migration mismatch")
        if any(report["catalogBaselineSha256"] != sha for report in migrated.values()):
            raise ValueError("live durable migration binding mismatch")
        return dict(durableReplayVerified=True, gitTransferVerified=True,
                    simulatedDeploymentVerified=accepted["deploymentVerified"],
                    durableMigrationVerified=True, temporaryOnly=True)
