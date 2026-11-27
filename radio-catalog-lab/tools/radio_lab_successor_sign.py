"""Protected real successor signing from the accepted state and public history.

No remote writes in this job. All five operation families are independently
requalified. The only exported payload is the verified public signed snapshot.
"""
import argparse
import datetime as dt
import os
import tempfile
from pathlib import Path

from radio_daily_baseline_verify import strict_json, verify_baseline, cli_anchor
from radio_daily_v9_generator import BASELINE, digest, encode
from radio_daily_git_lab_transport import snapshot, REF
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_github_readback import GitHubReadback
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_publication_simulator import inventory
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_live_release_preview import qualify_operations
from radio_daily_live_combined_preview import ORDER, inventory as operation_objects
from radio_daily_combined_release_validation import compose, publish_combined
from radio_daily_protected_signer import load_signer
from radio_daily_state_snapshot import bounded, transition
from radio_lab_first_release import pin, write_bundle


def restore_history(files, db, sequence):
    """Restore authenticated history and immutable artwork without the private key."""
    p=files["history/8.json"]
    body=files[strict_json(p)["content_path"]]
    legacy={}
    objects={}
    for logo,name in inventory(strict_json(body)):
        filename=logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]]
        data=files["objects/sha256/"+filename]
        if name is None:
            legacy[logo["url"]]=data
        else:
            objects[name]=data
    store=DurableLabStore.initialize(db,p,body,legacy_logos=legacy,objects=objects,**pin())
    for name,data in files.items():
        if name.startswith(("releases/","objects/sha256/")):
            store.put_immutable(name,data)
    for seq in range(9,sequence+1):
        store.compare_and_swap(store.current(),files["history/"+str(seq)+".json"])
    return store


def accepted_state(state):
    pointer=bounded(state/"release-anchor.json",16384)
    body=bounded(state/"release-baseline.json",10485760)
    context=strict_json(bounded(state/"release-context.json",1048576))
    p=strict_json(pointer)
    anchor=cli_anchor(p["content_sha256"],p["release_sequence"])
    if (p["release_sequence"]<9 or context["selectedSha256"]!=p["content_sha256"]
            or context["selectedSequence"]!=p["release_sequence"]
            or context["remoteReadbackVerified"] is not True
            or context["deploymentVerified"] is not True
            or context["simulated"] is not False):
        raise ValueError("accepted real state required")
    verify_baseline(pointer,body,**anchor)
    return pointer,body,context,anchor


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("state","reports","bundle","receipt","next-state"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    token=os.environ.pop("RADIO_LAB_JOB_TOKEN")
    encrypted=os.environ.pop("RADIO_LAB_ENCRYPTED_KEY")
    password=os.environ.pop("RADIO_LAB_PASSPHRASE").encode()
    pointer,raw,context,anchor=accepted_state(a.state)
    commit=context["gitCommit"]
    reader=GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
    def head():
        return reader.read_head(DESTINATION,REF)
    files=reader.read_tree(DESTINATION,commit)
    selected=verify_snapshot_entries({p:len(b) for p,b in files.items()},files.__getitem__,head,
        expected_commit=commit,bootstrap_sha=BASELINE,**anchor)
    if selected["pointer"]!=pointer or selected["body"]!=raw:
        raise ValueError("accepted state and remote history differ")
    def read(name):
        return strict_json(bounded(a.reports/name,12*1024*1024))
    day=dt.datetime.now(dt.timezone.utc).date().isoformat()
    discovery=read("candidates.json")
    if discovery["scanDate"]!=day:
        raise ValueError("fresh same-day collection required")
    if (a.reports/"release-anchor.json").read_bytes()!=pointer:
        raise ValueError("collection used a different predecessor")
    results,operations=qualify_operations(pointer,raw,anchor=anchor,day=day,
        discovery=discovery,dossiers=read("qualification-dossiers.json"),
        maintenance=read("maintenance-preview.json"),repair=read("repair-preview.json"),
        confirmation=read("repair-confirmation-preview.json"),logo_maintenance=read("logo-maintenance-preview.json"),
        missing_logo=read("missing-logo-preview.json"),status=read("status-transition-preview.json"))
    chosen={}
    candidate=None
    for kind in ORDER:
        if kind not in operations:
            continue
        trial=dict(chosen,**{kind:operations[kind]})
        try:
            body=compose(pointer,raw,anchor=anchor,day=day,operations=trial,objects=operation_objects(trial))
        except ValueError:
            continue
        chosen,candidate=trial,body
    seq=anchor["expected_sequence"]
    if head()!=commit:
        raise ValueError("remote changed during qualification")
    if candidate is None:
        a.receipt.write_bytes(encode(dict(changed=False,sequence=seq,sha256=anchor["expected_sha"],parent=commit)))
        print("RADIO_LAB_NO_CHANGE",seq)
        return
    signer=load_signer(encrypted,password,expected_public_key=pin()["public_key"],expected_key_id=pin()["key_id"])
    with tempfile.TemporaryDirectory() as temp:
        store=restore_history(files,Path(temp)/"history.sqlite",seq)
        if snapshot(store,seq)!=files:
            raise ValueError("restored prior history differs")
        publish_combined(store,signer,pointer,raw,candidate,
            expected_sha=anchor["expected_sha"],expected_sequence=seq,
            expected_candidate_sha=digest(candidate),day=day,operations=chosen,objects=operation_objects(chosen))
        # Build compatible successor state before allowing the signed bundle to leave.
        migration=transition(a.state,a.next_state,store.current(),lambda path,length:candidate,day=day,anchor=anchor)
        if migration["selectedSequence"]!=seq+1 or head()!=commit:
            raise ValueError("successor state or remote anchor changed")
        write_bundle(a.bundle,snapshot(store,seq+1))
    a.receipt.write_bytes(encode(dict(changed=True,sequence=seq+1,sha256=digest(candidate),parent=commit)))
    print("RADIO_LAB_SIGNED_SUCCESSOR",seq+1,digest(candidate),sorted(chosen))


if __name__=="__main__":
    main()
