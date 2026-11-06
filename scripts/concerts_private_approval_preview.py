#!/usr/bin/env python3
"""Read-only private Concert approvals PR preflight, run by trusted PUBLIC main.

No pull_request or untrusted code is executed with a private token. Only the
private JSON data is fetched from an exact same-repo PR head SHA. No private
payloads, URLs, source proofs or errors are written into public logs/artifacts.
This cannot sign a concert: it verifies existing independent signed proofs.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from scripts import concerts_cloud_sync as sync

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/Sarogal/GrossesOndes"
FILE = "automation/concerts/approved.json"
ALLOWED = re.compile(r"automation/concerts/test_[a-z0-9_]+\.py\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(value, message="Validation privée refusée"):
    if not value:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_only(previous, proposed, published):
    """Accept only a small, cumulative, independently signed *data* append."""
    require(isinstance(previous, dict) and isinstance(proposed, dict))
    require(previous.keys() == proposed.keys(),
            "Structure d'approbations altérée")
    require(all(previous[k] == proposed[k]
                for k in previous if k != "approvals"),
            "Données ou validation de salle modifiées")
    old = previous.get("approvals")
    new = proposed.get("approvals")
    require(isinstance(old, list) and isinstance(new, list))
    require(new[:len(old)] == old, "Historique des signatures modifié")
    fresh = new[len(old):]
    require(1 <= len(fresh) <= sync.MAX_NEW_EVENTS_PER_SYNC,
            "Lot nouveau trop important ou vide")
    old_ids = [r.get("event", {}).get("id") for r in old]
    all_ids = [r.get("event", {}).get("id") for r in new]
    require(len(all_ids) == len(set(all_ids))
            and all(isinstance(i, str) and i for i in all_ids),
            "Identifiants d'approbation en double")
    require(all(r.get("reviewDecision") == "approved"
                and r.get("reviewedBy") == "independent-official-verifier"
                and r.get("newArtists") == []
                and len(r.get("officialEvidence") or []) >= 2
                and isinstance(r.get("event"), dict)
                for r in fresh),
            "Lot privé sans signatures indépendantes ou changement d'artiste")
    current_ids = {r.get("id") for r in published.get("events", [])}
    require(all(r["event"]["id"] not in current_ids for r in fresh),
            "Concert déjà publié sous le même identifiant")
    return [r["event"]["id"] for r in fresh]


def audit(previous, proposed, reference, published, today):
    fresh_ids = append_only(previous, proposed, published)
    merged, counts = sync.merge(reference, published, proposed, today)
    require(counts.get("newEvents") == len(fresh_ids)
            and counts.get("newArtists") == 0
            and counts.get("newVenues") == 0
            and counts.get("correctedEvents") == 0
            and counts.get("correctedVenues") == 0
            and not counts.get("held"),
            "Simulation de publication différente du lot approuvé")
    require([e["id"] for e in merged["events"][len(published["events"]):]]
            == fresh_ids, "L'ordre et les IDs des événements changent")
    require(merged["events"][:len(published["events"])]
            == published["events"], "Concert historique ou publié altéré")
    require(merged["artists"] == published["artists"]
            and merged["venues"] == published["venues"],
            "Identité artistique ou géolocalisation modifiée")
    require(len(merged["events"]) == len(published["events"]) + len(fresh_ids),
            "Nombre d'événements inattendu")
    sync.protect_reference(reference, merged)
    sync.validate_catalogue(merged)
    return len(fresh_ids)


def github_json(path, token):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GrossesOndes-private-approval-readonly-preview",
        })
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read(3_000_001)
    require(len(raw) < 3_000_001, "Réponse API anormalement volumineuse")
    return json.loads(raw)


def github_approval(ref, token):
    require(SHA.fullmatch(ref), "Référence Git inconnue")
    meta = github_json("/contents/" + FILE + "?ref=" +
                       urllib.parse.quote(ref, safe=""), token)
    require(meta.get("type") == "file" and meta.get("encoding") == "base64",
            "Fichier d'approbations introuvable")
    content = base64.b64decode(meta["content"], validate=False)
    require(len(content) <= 2_000_000, "Approbations excessivement volumineuses")
    return json.loads(content.decode("utf-8"))


def preview(pr_number, token, today):
    require(re.fullmatch(r"[1-9][0-9]{0,5}", pr_number),
            "Numéro de PR invalide")
    number = int(pr_number)
    pr = github_json("/pulls/" + str(number), token)
    require(pr.get("state") == "open"
            and pr.get("base", {}).get("ref") == "main"
            and pr.get("head", {}).get("repo", {}).get("full_name")
                == "Sarogal/GrossesOndes"
            and pr.get("base", {}).get("repo", {}).get("full_name")
                == "Sarogal/GrossesOndes",
            "PR privée non autorisée")
    head = pr["head"]["sha"]
    main = github_json("/branches/main", token)["commit"]["sha"]
    require(SHA.fullmatch(head) and SHA.fullmatch(main),
            "Références Git invalides")
    # A PR cannot smuggle executable scripts/workflows into this validation.
    changed = github_json("/pulls/" + str(number) + "/files?per_page=100", token)
    require(isinstance(changed, list) and 1 <= len(changed) <= 20
            and {f["filename"] for f in changed}.issuperset({FILE})
            and all(f["filename"] == FILE
                    or ALLOWED.fullmatch(f["filename"])
                    for f in changed),
            "La PR modifie des fichiers hors périmètre")
    previous = github_approval(main, token)
    proposed = github_approval(head, token)
    reference = read_json(ROOT / "docs/grossesondes/concerts-reference.json")
    published = read_json(ROOT / "docs/grossesondes/concerts.json")
    return audit(previous, proposed, reference, published, today)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", required=True)
    args = parser.parse_args()
    # The read token lives in the trusted, main-only job environment.
    # Never echo it or a private API response.
    token = os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN", "")
    if not token:
        print("::error::Accès privé de lecture indisponible", file=sys.stderr)
        return 1
    try:
        checked = preview(
            args.pr_number, token,
            dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    except Exception:
        print("::error::Prévalidation refusée ; aucun détail privé diffusé",
              file=sys.stderr)
        return 1
    print("Prévalidation privée réussie en lecture seule : "
          + str(checked) + " nouveaux concerts, sans publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
