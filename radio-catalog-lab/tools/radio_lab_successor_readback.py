"""Independently accept an actual successor and reconstruct compatible state.

This job has read-only credentials. The deployment record and Git state
commit occur later, only after acceptance of the exact signed bytes.
"""
import argparse
import datetime as dt
import os
import time
from pathlib import Path

from radio_daily_baseline_verify import strict_json
from radio_daily_v9_generator import BASELINE, encode
from radio_daily_git_lab_transport import REF
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_github_readback import GitHubReadback
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_publication_simulator import inventory, check_logo
from radio_daily_logo_plan import EXTENSIONS
from radio_daily_deployment_verify import verify_public_snapshot, mirror_url, ROOT, POINTER_URL
from radio_daily_public_https_reader import PublicHTTPSReader
from radio_daily_state_snapshot import bounded, transition
from radio_lab_first_release import pin
from radio_lab_successor_sign import accepted_state


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("state","transfer-receipt","acceptance","next-state"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    token=os.environ.pop("RADIO_LAB_JOB_TOKEN")
    prior,raw,context,anchor=accepted_state(a.state)
    receipt=strict_json(bounded(a.transfer_receipt,16384))
    seq=anchor["expected_sequence"]
    if receipt["parent"]!=context["gitCommit"] or receipt["sequence"]!=seq+1:
        raise ValueError("unexpected successor receipt")
    commit=receipt["commit"]
    reader=GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
    def head():
        return reader.read_head(DESTINATION,REF)
    files=reader.read_tree(DESTINATION,commit)
    selected=verify_snapshot_entries({p:len(b) for p,b in files.items()},files.__getitem__,head,
        expected_commit=commit,bootstrap_sha=BASELINE,**anchor)
    if (selected["sequence"]!=seq+1 or selected["sha256"]!=receipt["sha256"]
            or selected["anchor_pointer"]!=prior or selected["anchor_body"]!=raw):
        raise ValueError("remote successor does not match accepted predecessor")
    p=strict_json(selected["pointer"])
    resources={POINTER_URL:16384,ROOT+p["content_path"]:p["content_length"]}
    for logo,_ in inventory(strict_json(selected["body"])):
        url=mirror_url(logo)
        if url in resources and resources[url]!=logo["byte_size"]:
            raise ValueError("conflicting public artwork length")
        resources[url]=logo["byte_size"]
    for attempt in range(3):
        try:
            accepted=verify_public_snapshot(selected,head,fetch=PublicHTTPSReader(resources,max_seconds=300),
                expected_commit=commit,mirror_legacy=True,**pin())
            break
        except (OSError,ValueError):
            if attempt==2 or head()!=commit:
                raise
            time.sleep(15*(attempt+1))
    day=dt.datetime.now(dt.timezone.utc).date().isoformat()
    migration=transition(a.state,a.next_state,selected["pointer"],
        lambda path,length:selected["body"],day=day,anchor=anchor)
    if migration["selectedSequence"]!=seq+1 or migration["selectedSha256"]!=receipt["sha256"] or head()!=commit:
        raise ValueError("independent successor state mismatch")
    # Seed missing new immutable objects in the same verified state artifact.
    cache=a.next_state/"artwork-cache"/"sha256"
    for logo,_ in inventory(strict_json(selected["body"])):
        name=logo["sha256"]+"."+EXTENSIONS[logo["mime_type"]]
        previous=a.state/"artwork-cache"/"sha256"/name
        if previous.is_file() and not previous.is_symlink():
            check_logo(logo,previous.read_bytes())
            continue
        data=files["objects/sha256/"+name]
        check_logo(logo,data)
        cache.mkdir(parents=True,exist_ok=True)
        (cache/name).write_bytes(data)
    # Do not call it a recorded deployment until the later deployment job.
    accepted.update(simulated=False,remoteReadbackVerified=True,
        distribution="github-raw",legacyOriginalUrlsVerified=False,parent=receipt["parent"])
    a.acceptance.write_bytes(encode(accepted))
    print("RADIO_LAB_SUCCESSOR_ACCEPTED",seq+1,receipt["sha256"],accepted["verifiedLogoUrls"])


if __name__=="__main__":
    main()
