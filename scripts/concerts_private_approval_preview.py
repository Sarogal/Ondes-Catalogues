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
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
# Direct invocation as python scripts/...py must see the trusted repository root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import concerts_cloud_sync as sync
API = "https://api.github.com/repos/Sarogal/GrossesOndes"
FILE = "automation/concerts/approved.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")


def require(value, message="Validation privée refusée"):
    if not value:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def approved_delta(previous, proposed, published):
    """Inspect a single append-only change. The trusted publisher is the authority."""
    require(isinstance(previous, dict) and isinstance(proposed, dict))
    require(previous.keys() == proposed.keys(),
            "Structure d'approbations altérée")
    permitted = {"approvals", "referenceEventStatusCorrections"}
    require(all(previous[k] == proposed[k] for k in previous if k not in permitted),
            "Données historiques ou validations de salle modifiées")

    old = previous.get("approvals")
    new = proposed.get("approvals")
    require(isinstance(old, list) and isinstance(new, list))
    require(new[:len(old)] == old, "Historique des signatures modifié")
    fresh = new[len(old):]
    require(len(fresh) <= sync.MAX_NEW_EVENTS_PER_SYNC,
            "Lot nouveau trop important")

    old_status = previous.get("referenceEventStatusCorrections", [])
    new_status = proposed.get("referenceEventStatusCorrections", [])
    require(isinstance(old_status, list) and isinstance(new_status, list)
            and new_status[:len(old_status)] == old_status,
            "Historique des corrections de statut modifié")
    added_status = new_status[len(old_status):]
    require(len(added_status) <= 1 and bool(fresh) != bool(added_status),
            "Une seule catégorie de modification, non vide, est autorisée")
    all_ids = [r.get("event", {}).get("id") if isinstance(r, dict) else None
               for r in new]
    require(len(all_ids) == len(set(all_ids))
            and all(isinstance(i, str) and i for i in all_ids),
            "Identifiants d'approbation en double")
    require(all(
        isinstance(r, dict)
        and r.get("reviewDecision") == "approved"
        and r.get("reviewedBy") in (
            "independent-official-verifier", "automated-official-recheck")
        and isinstance(r.get("officialEvidence"), list)
        and bool(r["officialEvidence"])
        and isinstance(r.get("event"), dict)
        and isinstance(r.get("newArtists", []), list)
        for r in fresh
    ), "Lot privé sans approbation ou preuve officielle")
    current_ids = {r.get("id") for r in published.get("events", [])}
    require(all(r["event"]["id"] not in current_ids for r in fresh),
            "Concert déjà publié sous le même identifiant")
    require(all(
        isinstance(r, dict)
        and isinstance(r.get("eventId"), str)
        and r["eventId"] in current_ids
        and r.get("reviewDecision") == "approved"
        and r.get("reviewedBy") == "independent-official-verifier"
        and isinstance(r.get("eventPatch"), dict)
        and isinstance(r.get("officialEvidence"), list)
        and bool(r["officialEvidence"])
        for r in added_status
    ), "Correction de statut sans signature indépendante")
    # No other correction is authorized here; the real sync.merge() verifies
    # the exact signed event, provenance and permitted immutable-state change.
    return [r["event"]["id"] for r in fresh], added_status


def append_only(previous, proposed, published):
    """Backwards-compatible API used by the original safety tests."""
    ids, _ = approved_delta(previous, proposed, published)
    return ids


def audit(previous, proposed, reference, published, today):
    fresh_ids, added_status = approved_delta(previous, proposed, published)
    merged, counts = sync.merge(reference, published, proposed, today)
    expected_artists = [
        a.get("id") if isinstance(a, dict) else None
        for row in proposed["approvals"][len(previous["approvals"]):]
        for a in row.get("newArtists", [])
    ]
    require(all(isinstance(a, str) and a for a in expected_artists)
            and len(expected_artists) == len(set(expected_artists)),
            "Nouveaux artistes non identifiés")
    require(counts.get("newEvents") == len(fresh_ids)
            and counts.get("newArtists") == len(expected_artists)
            and counts.get("newVenues") == 0
            and counts.get("correctedEvents") == len(added_status)
            and counts.get("correctedVenues") == 0
            and not counts.get("held"),
            "Simulation de publication différente du lot approuvé")
    old_events = published["events"]
    new_events = merged["events"]
    require(len(new_events) == len(old_events) + len(fresh_ids)
            and [e["id"] for e in new_events[len(old_events):]] == fresh_ids,
            "Ordre, identifiants ou nombre d'événements modifiés")
    if added_status:
        target = added_status[0]["eventId"]
        changed = [(old, new) for old, new in zip(old_events, new_events)
                   if old != new]
        require(len(changed) == 1
                and changed[0][0]["id"] == changed[0][1]["id"] == target,
                "Correction d'un événement non signé")
        old, new = changed[0]
        allowed = {"status", "lastVerified", "cancellationSourceUrl", "history"}
        require(all(old.get(k) == new.get(k)
                    for k in set(old) | set(new) if k not in allowed),
                "Correction de statut modifiant des données immuables")
    else:
        require(new_events[:len(old_events)] == old_events,
                "Concert historique ou publié altéré")
    old_artists = published["artists"]
    new_artists = merged["artists"]
    require(new_artists[:len(old_artists)] == old_artists
            and [a["id"] for a in new_artists[len(old_artists):]]
                == expected_artists,
            "Identités artistiques différentes des signatures")
    require(merged["venues"] == published["venues"],
            "Géolocalisation ou salle modifiée")
    sync.protect_reference(reference, merged)
    sync.validate_catalogue(merged)
    return len(fresh_ids) + len(added_status)


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
    require(bool(SHA.fullmatch(ref)) or ref == "main",
            "Référence Git inconnue")
    meta = github_json("/contents/" + FILE + "?ref=" +
                       urllib.parse.quote(ref, safe=""), token)
    require(meta.get("type") == "file" and meta.get("encoding") == "base64",
            "Fichier d'approbations introuvable")
    content = base64.b64decode(meta["content"], validate=False)
    require(len(content) <= 2_000_000, "Approbations excessivement volumineuses")
    return json.loads(content.decode("utf-8"))


class PrivatePreviewStageError(RuntimeError):
    """Only the fixed stage code, never a private exception message."""
    def __init__(self, stage):
        self.stage = stage
        super().__init__(stage)


def guarded(stage, callback):
    try:
        return callback()
    except Exception:
        raise PrivatePreviewStageError(stage) from None


def preview(head_sha, token, today):
    # A trusted operator copies the exact head SHA from the *private* PR.
    # Only the approved JSON blob is read. No PR branch code is checked out,
    # and only a repository-contents:read token is needed.
    require(isinstance(head_sha, str) and SHA.fullmatch(head_sha),
            "Référence Git privée invalide")
    previous = guarded("READ_MAIN", lambda: github_approval("main", token))
    proposed = guarded("READ_HEAD", lambda: github_approval(head_sha, token))
    reference = guarded("READ_PUBLIC", lambda: read_json(
        ROOT / "docs/grossesondes/concerts-reference.json"))
    published = guarded("READ_PUBLIC", lambda: read_json(
        ROOT / "docs/grossesondes/concerts.json"))
    return guarded("MERGE", lambda: audit(previous, proposed, reference, published, today))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    # The read token lives in the trusted, main-only job environment.
    # Never echo it or a private API response.
    token = os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN", "")
    if not token:
        print("::error::Accès privé de lecture indisponible", file=sys.stderr)
        return 1
    try:
        checked = preview(
            args.head_sha, token,
            dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    except PrivatePreviewStageError as failure:
        # Fixed vocabulary is safe for public Actions logs. Never print the
        # suppressed exception or its possibly confidential validation context.
        print("PREVIEW_STAGE=" + failure.stage, file=sys.stderr)
        return 1
    except Exception:
        print("PREVIEW_STAGE=UNEXPECTED", file=sys.stderr)
        return 1
    print("Prévalidation privée réussie en lecture seule : "
          + str(checked) + " modification(s) vérifiée(s), sans publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
