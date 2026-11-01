#!/usr/bin/env python3
"""Preview or safely stage official-approved concerts into the public Pages catalogue.

The only permitted output path is docs/grossesondes/concerts.json. No remote write.
A publication is handled separately by GitHub Actions after explicit variable gating.
"""
import argparse
import base64
import copy
import datetime as dt
import json
import os
from pathlib import Path
import urllib.request

CATALOGUE = Path("docs/grossesondes/concerts.json")
APPROVAL_URL = "https://api.github.com/repos/Sarogal/GrossesOndes/contents/automation/concerts/approved.json?ref=main"


def approvals_from_github():
    token = os.environ.get("GROSSES_ONDES_INTAKE_READ_TOKEN", "")
    if not token:
        raise RuntimeError("Missing private GitHub read token")
    request = urllib.request.Request(APPROVAL_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GrossesOndesConcertApprovedSync/1.0",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    return json.loads(base64.b64decode(payload["content"]).decode("utf-8"))


def merge(catalogue, approvals):
    data = copy.deepcopy(catalogue)
    if data.get("schemaVersion") != 1 or data.get("mode") != "preview-public-unlisted":
        raise ValueError("Unexpected catalogue format")
    if approvals.get("schema") != "grossesondes.concert.approvals.v1":
        raise ValueError("Unexpected approvals schema")
    events = data["events"]
    artists = {a["id"]: a for a in data["artists"]}
    venues = {v["id"] for v in data["venues"]}
    ids = {e["id"]: e for e in events}
    signatures = {(e["date"], e["venueId"], e["title"].casefold().strip()) for e in events}
    added, skipped = [], []
    for item in approvals.get("approvals", []):
        if item.get("reviewDecision") != "approved" or item.get("reviewedBy") != "independent-official-verifier" or not item.get("reviewedAt"):
            raise ValueError("Approval not independently verified")
        e = copy.deepcopy(item["event"])
        if e.get("status") != "confirmed":
            raise ValueError("Unconfirmed event")
        if not e.get("id") or not e.get("title") or e.get("venueId") not in venues or not e.get("artistIds"):
            raise ValueError("Missing or invalid event identity")
        dt.date.fromisoformat(e["date"])
        url = e.get("officialUrl", "")
        if not url.startswith("https://") or not any(
            proof.get("url") == url
            and proof.get("proofType") == "official-organizer-or-venue"
            and {"artists", "date", "venue"}.issubset(set(proof.get("checkedFields", [])))
            for proof in item.get("officialEvidence", [])
        ):
            raise ValueError("Insufficient official evidence")
        additions = {a["id"]: a for a in item.get("newArtists", [])}
        for artist_id in e["artistIds"]:
            if artist_id not in artists and artist_id not in additions:
                raise ValueError("Unrecognized artist " + artist_id)
            if artist_id in artists and artist_id in additions and artists[artist_id]["name"] != additions[artist_id]["name"]:
                raise ValueError("Conflicting artist identity")
        signature = (e["date"], e["venueId"], e["title"].casefold().strip())
        if e["id"] in ids:
            existing = ids[e["id"]]
            if (existing["date"], existing["venueId"], existing["title"].casefold().strip()) != signature:
                raise ValueError("Event ID collision")
            skipped.append(e["id"])
            continue
        if signature in signatures:
            skipped.append(e["id"])
            continue
        for artist_id in e["artistIds"]:
            if artist_id not in artists:
                artist = additions[artist_id]
                data["artists"].append(artist)
                artists[artist_id] = artist
        e["timeMeaning"] = e.get("timeMeaning") if e.get("time") else None
        e.setdefault("ticketUrl", None)
        e["lastVerified"] = item["reviewedAt"]
        e["confidence"] = "Annonce officielle vérifiée indépendamment"
        e["sourceLabel"] = "Salle ou organisateur officiel"
        e["history"] = [{"date": item["reviewedAt"], "change": "Vérification indépendante sur la page officielle"}]
        events.append(e)
        ids[e["id"]] = e
        signatures.add(signature)
        added.append(e["id"])
    events.sort(key=lambda e: (e["date"], e["id"]))
    if len(events) < len(catalogue["events"]):
        raise ValueError("Unexpected loss of existing concerts")
    return data, {"added": added, "already_present": skipped, "total": len(events)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "stage"), default="preview")
    parser.add_argument("--out", default="/tmp/grossesondes_concerts_preview.json")
    parser.add_argument("--report", default="/tmp/grossesondes_concerts_report.json")
    args = parser.parse_args()
    before = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    after, report = merge(before, approvals_from_github())
    Path(args.out).write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.mode == "stage" and report["added"]:
        CATALOGUE.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
