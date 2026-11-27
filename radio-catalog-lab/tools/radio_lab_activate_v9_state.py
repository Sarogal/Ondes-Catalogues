"""One-time migration from immutable TEST V8 to independently accepted real V9.

The only write is a local state snapshot; the workflow commits it on the
separate autonomous state ref. No private key or catalogue write is needed.
"""
import argparse
import datetime as dt
import os
from pathlib import Path

from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import BASELINE, encode, digest
from radio_daily_git_lab_transport import REF
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_github_readback import GitHubReadback
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_deployment_verify import verify_public_snapshot, mirror_url, ROOT, POINTER_URL
from radio_daily_public_https_reader import PublicHTTPSReader, deployment_status, API
from radio_daily_publication_simulator import inventory
from radio_daily_baseline_verify import strict_json
from radio_daily_state_snapshot import transition, bounded
from radio_lab_first_release import TEST_ANCHOR, pin

V9 = "08f25acfab1d8dd8617206939f50bb7d2c86d0e7f06d7ccaf064110db732ce67"
COMMIT = "85704d48a7f669de79265ff45b39027b55fe27af"
DEPLOYMENT = 8106061515


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("previous","output","test-body","test-pointer"):
        p.add_argument("--"+name, type=Path, required=True)
    args = p.parse_args()
    if (os.environ.get("GITHUB_REPOSITORY") != "Sarogal/Ondes-Catalogues"
            or os.environ.get("GITHUB_REF") != "refs/heads/feature/radio-daily-discovery-lab-20261120"
            or os.environ.get("GITHUB_ACTIONS") != "true"):
        raise ValueError("isolated Actions context required")
    token = os.environ.pop("RADIO_LAB_JOB_TOKEN")
    old = bounded(args.test_body,10485760)
    test_pointer = bounded(args.test_pointer,16384)
    verify_baseline(test_pointer,old,**TEST_ANCHOR)
    if bounded(args.previous/"release-anchor.json",16384) != test_pointer:
        raise ValueError("previous state not bound to immutable TEST pointer")
    reader = GitHubReadback(GitHubJSONReader(token=token,max_seconds=600))
    def head():
        return reader.read_head(DESTINATION,REF)
    files = reader.read_tree(DESTINATION,COMMIT)
    anchor = dict(expected_sha=BASELINE,expected_sequence=8,**pin())
    selected = verify_snapshot_entries({path:len(data) for path,data in files.items()},
        files.__getitem__,head,expected_commit=COMMIT,bootstrap_sha=BASELINE,**anchor)
    if selected["sha256"] != V9 or selected["sequence"] != 9 or selected["anchor_body"] != old:
        raise ValueError("unexpected V9 migration anchor")
    endpoint=API+str(DEPLOYMENT)
    deployment_status(PublicHTTPSReader({endpoint:1048576,endpoint+"/statuses":1048576}),
        deployment_id=DEPLOYMENT,expected_commit=COMMIT,
        expected_ref=REF.removeprefix("refs/heads/"),environment=REF.removeprefix("refs/heads/"))
    pointer = strict_json(selected["pointer"])
    resources={POINTER_URL:16384,ROOT+pointer["content_path"]:pointer["content_length"]}
    for logo,_ in inventory(strict_json(selected["body"])):
        url=mirror_url(logo)
        if url in resources and resources[url]!=logo["byte_size"]:
            raise ValueError("conflicting mirror size")
        resources[url]=logo["byte_size"]
    accepted=verify_public_snapshot(selected,head,fetch=PublicHTTPSReader(resources,max_seconds=300),
        expected_commit=COMMIT,mirror_legacy=True,**pin())
    # Reanchor the locally verified identical V8 bytes, not the old TEST key.
    # Only this working copy changes. The predecessor state branch is untouched.
    (args.previous/"release-anchor.json").write_bytes(selected["anchor_pointer"])
    (args.previous/"release-baseline.json").write_bytes(old)
    day=dt.datetime.now(dt.timezone.utc).date().isoformat()
    context=transition(args.previous,args.output,selected["pointer"],
        lambda path,length:selected["body"],day=day,anchor=anchor)
    if context["selectedSha256"]!=V9 or context["selectedSequence"]!=9 or head()!=COMMIT:
        raise ValueError("state transition anchor mismatch")
    context.update(gitCommit=COMMIT,deploymentId=DEPLOYMENT,remoteReadbackVerified=True,
        deploymentVerified=True,simulated=False,mirroredLegacyArtwork=True)
    (args.output/"release-context.json").write_bytes(encode(context))
    print("RADIO_LAB_REAL_STATE_MIGRATED",V9,len(context["migratedFiles"]),
        "public artwork",accepted["verifiedLogoUrls"])


if __name__=="__main__":
    main()
