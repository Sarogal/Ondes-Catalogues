"""One-time local GitHub admin setup for the isolated radio rehearsal.

Run on the owner's authenticated workstation; never in Actions or in chat.
Creates only three branch-restricted environments and an independent signing
identity. Does not create the publication ref, dispatch or publish anything.
"""
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, BestAvailableEncryption,
)

REPO = "Sarogal/Ondes-Catalogues"
BASE = "repos/" + REPO
BRANCH = "feature/radio-daily-discovery-lab-20261120"
ENVIRONMENTS = ("radio-lab-signing", "radio-lab-transport", "radio-lab-readback")
KEY_NAMES = {"RADIO_LAB_ENCRYPTED_KEY", "RADIO_LAB_PASSPHRASE"}
PIN_NAMES = {"RADIO_LAB_PUBLIC_KEY", "RADIO_LAB_KEY_ID"}


def gh(*args, data=None):
    result = subprocess.run(["gh", *args], input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        # Do not forward credential-bearing output from external commands.
        raise RuntimeError("GitHub CLI operation failed: " + args[0])
    return result.stdout


def api(path, method="GET", body=None):
    args = ["api", "--method", method, path]
    data = None
    if body is not None:
        args += ["--input", "-"]
        data = json.dumps(body).encode()
    output = gh(*args, data=data)
    return json.loads(output) if output else {}


def main():
    if os.environ.get("GITHUB_ACTIONS"):
        raise RuntimeError("local owner workstation required")
    if sys.argv[1:] != ["--activate-isolated-lab"]:
        raise RuntimeError("explicit local activation flag required")
    owner = api("user")["login"]
    repo = api(BASE)
    if (owner.lower() != "sarogal" or repo["id"] != 1438875064
            or repo["private"] or not repo.get("permissions", {}).get("admin")):
        raise RuntimeError("expected repository owner/admin required")
    # Never rotate or overwrite existing identity, including a partial setup.
    existing = {v["name"] for v in api(BASE+"/actions/variables")["variables"]}
    if PIN_NAMES & existing:
        raise RuntimeError("existing or partial lab public pin; do not overwrite")
    envs = {v["name"] for v in api(BASE+"/environments")["environments"]}
    for name in ENVIRONMENTS:
        if name in envs:
            detail = api(BASE+"/environments/"+name)
            policy = detail.get("deployment_branch_policy") or {}
            rules = api(BASE+"/environments/"+name+"/deployment-branch-policies")["branch_policies"]
            if (policy.get("custom_branch_policies") is not True
                    or policy.get("protected_branches") is not False
                    or [(r["name"], r.get("type", "branch")) for r in rules] != [(BRANCH, "branch")]):
                raise RuntimeError("existing environment policy differs: "+name)
            if name == "radio-lab-signing":
                names = {s["name"] for s in api(BASE+"/environments/"+name+"/secrets")["secrets"]}
                if KEY_NAMES & names:
                    raise RuntimeError("existing or partial signing key; do not overwrite")
    for name in ENVIRONMENTS:
        if name not in envs:
            path = BASE+"/environments/"+name
            api(path, "PUT", {"deployment_branch_policy":{
                "protected_branches":False, "custom_branch_policies":True}})
            api(path+"/deployment-branch-policies", "POST", {"name":BRANCH,"type":"branch"})
        path = BASE+"/environments/"+name
        rules = api(path+"/deployment-branch-policies")["branch_policies"]
        if [(r["name"], r.get("type", "branch")) for r in rules] != [(BRANCH,"branch")]:
            raise RuntimeError("environment restriction not verified")
    key = Ed25519PrivateKey.generate()
    password = secrets.token_urlsafe(48).encode("ascii")
    encrypted = base64.b64encode(key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(password)))
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    kid = "radio-lab-"+hashlib.sha256(public).hexdigest()[:24]
    # Public pin independent of artifact and key secret. No key in argv,
    # stdout, workspace, files, or git. Stop on a partially failed setup.
    gh("variable","set","RADIO_LAB_PUBLIC_KEY","--repo",REPO,
       "--body",base64.b64encode(public).decode("ascii"))
    gh("variable","set","RADIO_LAB_KEY_ID","--repo",REPO,"--body",kid)
    gh("secret","set","RADIO_LAB_ENCRYPTED_KEY","--repo",REPO,
       "--env","radio-lab-signing",data=encrypted)
    gh("secret","set","RADIO_LAB_PASSPHRASE","--repo",REPO,
       "--env","radio-lab-signing",data=password)
    names = {s["name"] for s in api(BASE+"/environments/radio-lab-signing/secrets")["secrets"]}
    if not KEY_NAMES <= names:
        raise RuntimeError("signing secret metadata not verified")
    print("RADIO_LAB_SETUP_OK", kid)
    print("No catalogue published. No TEST or production change.")


if __name__ == "__main__":
    main()
