"""Transfer a signed real successor only to the isolated publication ref.

No signing credentials are accepted. The accepted state anchors the exact
parent, and the public bundle must contain precisely one additional release.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from radio_daily_baseline_verify import strict_json
from radio_daily_v9_generator import BASELINE, encode
from radio_daily_git_lab_transport import LocalGitLabTransport, REF, snapshot
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_github_transfer_contract import DESTINATION, prepare
from radio_daily_github_executor import transmit_github
from radio_daily_github_readback import GitHubReadback
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_state_snapshot import bounded
from radio_lab_first_release import read_bundle, stage_deterministic
from radio_lab_successor_sign import accepted_state, restore_history


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("state","bundle","signed-receipt","transfer-receipt"):
        parser.add_argument("--"+name,type=Path,required=True)
    a=parser.parse_args()
    token=os.environ.pop("RADIO_LAB_JOB_TOKEN")
    prior,raw,context,anchor=accepted_state(a.state)
    receipt=strict_json(bounded(a.signed_receipt,16384))
    parent=context["gitCommit"]
    seq=anchor["expected_sequence"]
    if (receipt.get("changed") is not True or receipt.get("parent")!=parent
            or receipt.get("sequence")!=seq+1):
        raise ValueError("signed receipt is not direct successor")
    files=read_bundle(a.bundle)
    pseudo="1"*40
    selected=verify_snapshot_entries({p:len(b) for p,b in files.items()},files.__getitem__,
        lambda:pseudo,expected_commit=pseudo,bootstrap_sha=BASELINE,**anchor)
    if (selected["sequence"]!=seq+1 or selected["sha256"]!=receipt["sha256"]
            or selected["anchor_pointer"]!=prior or selected["anchor_body"]!=raw):
        raise ValueError("signed bundle does not match accepted parent")
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        store=restore_history(files,root/"history.sqlite",seq+1)
        if snapshot(store,seq+1)!=files:
            raise ValueError("restored successor bundle mismatch")
        bare=root/"source.git"
        env={k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",GIT_NO_REPLACE_OBJECTS="1")
        subprocess.run(["git","init","--bare","--template=","--object-format=sha1",str(bare)],
            check=True,capture_output=True,env=env,timeout=30)
        # Fetch only the authorized public ref. Preserve the exact original
        # parent commit; never reconstruct earlier Git history from timestamps.
        subprocess.run(["git","--git-dir="+str(bare),"-c","protocol.allow=never",
            "-c","protocol.https.allow=always","-c","http.followRedirects=false",
            "fetch","--no-tags","--no-recurse-submodules",DESTINATION,
            REF+":"+REF],check=True,capture_output=True,env=env,timeout=120)
        source=LocalGitLabTransport(bare)
        fetched=source.head()
        source._verify_tree(parent,snapshot(store,seq))
        if fetched!=parent:
            parents=source._git("rev-list","--parents","-n","1",fetched).decode().split()
            if parents!=[fetched,parent]:
                raise ValueError("unexpected competing remote successor")
            source._verify_tree(fetched,files)
            # Reuse the existing exact child after interruption.
            head=fetched
        else:
            head=stage_deterministic(source,store,seq+1,parent)
        plan=prepare(source,store,destination=DESTINATION,ref=REF,
            expected_commit=head,expected_remote_head=parent,expected_sequence=seq+1,
            expected_sha=selected["sha256"])
        reader=GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
        transmit_github(source,store,plan,read_head=reader.read_head,read_tree=reader.read_tree,
            write_token=token,authorized=True)
        a.transfer_receipt.write_bytes(encode(dict(commit=head,parent=parent,
            sequence=seq+1,sha256=selected["sha256"])))
        print("RADIO_LAB_SUCCESSOR_TRANSFERRED",seq+1,head)


if __name__=="__main__":
    main()
