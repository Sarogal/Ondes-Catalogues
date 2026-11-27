"""Dormant remote read-only acceptance using real GitHub/HTTPS reader contracts.

No write, deployment dispatch, secret discovery or publication activation.
The independently pinned key, prior digest and expected commit are mandatory.
"""
from radio_daily_baseline_verify import strict_json
from radio_daily_git_lab_reader import verify_snapshot_entries
from radio_daily_git_lab_transport import REF
from radio_daily_github_transfer_contract import DESTINATION
from radio_daily_github_readback import GitHubReadback
from radio_daily_public_https_reader import PublicHTTPSReader, deployment_status, API
from radio_daily_deployment_verify import verify_public_snapshot, ROOT, POINTER_URL
from radio_daily_publication_simulator import inventory


def verify_remote(*, reader, deployment_id, environment, expected_commit,
                  bootstrap_sha, expected_sha, expected_sequence, public_key, key_id):
    if not isinstance(reader, GitHubReadback):
        raise ValueError("independent GitHub reader required")
    if environment != "radio-lab-publisher-rehearsal":
        raise ValueError("unauthorized laboratory deployment environment")
    if type(deployment_id) is not int or deployment_id <= 0:
        raise ValueError("explicit deployment ID required")
    def head():
        return reader.read_head(DESTINATION, REF)
    if head() != expected_commit:
        raise ValueError("Git head anchor mismatch")
    files = reader.read_tree(DESTINATION, expected_commit)
    selected = verify_snapshot_entries({path:len(data) for path,data in files.items()},
        files.__getitem__, head, expected_commit=expected_commit, bootstrap_sha=bootstrap_sha,
        expected_sha=expected_sha, expected_sequence=expected_sequence,
        public_key=public_key, key_id=key_id)
    p = strict_json(selected["pointer"])
    resources = {POINTER_URL:16384, ROOT+p["content_path"]:p["content_length"]}
    for logo, _ in inventory(strict_json(selected["body"])):
        url = logo["url"]
        if url in resources and resources[url] != logo["byte_size"]:
            raise ValueError("conflicting public resource identity")
        resources[url] = logo["byte_size"]
    endpoint = API+str(deployment_id)
    status = deployment_status(PublicHTTPSReader({endpoint:1048576,endpoint+"/statuses":1048576}),
        deployment_id=deployment_id, expected_commit=expected_commit,
        expected_ref=REF.removeprefix("refs/heads/"), environment=environment)
    accepted = verify_public_snapshot(selected, head, fetch=PublicHTTPSReader(resources),
        expected_commit=expected_commit, public_key=public_key, key_id=key_id)
    return dict(accepted, simulated=False, deploymentId=status["deploymentId"],
                remoteReadbackVerified=True, publicationAllowed=False)
