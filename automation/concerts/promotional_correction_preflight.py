#!/usr/bin/env python3
"""Private append-only correction gate; never writes the public catalogue.

A proposal is not an approval. Run the existing trusted Publisher preview
on a single exact correction, then atomically append it only in apply mode.
Keep new event/site publication independent of this maintenance operation.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automation.concerts.approval_preflight import atomic_store
from automation.concerts.published_lineup_patch_builder import SCHEMA
from scripts import concert_published_lineup_contract as contract
from scripts import concerts_private_approval_preview as preview


def audit_correction(previous, proposed, reference, current, today):
    """Replay an exact correction even when a new-event batch is waiting.

    Compare the real Publisher with and without the sole appended correction.
    New concerts, venues, held decisions and other historical changes must
    be identical. This preserves the pending batch rather than bypassing it.
    """
    published_ids = {e["id"] for e in current["events"]}
    # An exclusion or artist retirement can be signed but not yet deployed.
    # The ordinary append-only preview cannot model those independent deltas.
    maintenance = (previous.get("editorialCorrections") or
                   previous.get("artistIdentityRetirements"))
    if not maintenance and all(a["event"]["id"] in published_ids
                               for a in previous["approvals"]):
        return preview.audit(previous, proposed, reference, current, today)
    fresh, statuses = preview.approved_delta(previous, proposed, current)
    added = proposed.get("lineupCorrections", [])[len(previous.get("lineupCorrections", [])):]
    preview.require(not fresh and not statuses and len(added) == 1,
                    "Expected exactly one appended correction")
    row = added[0]
    original = next(a for a in previous["approvals"] if a["event"]["id"] == row["eventId"])
    plan = contract.plan(row, original, current, today)
    before, before_counts = preview.sync.merge(reference, current, previous, today)
    after, after_counts = preview.sync.merge(reference, current, proposed, today)
    old = next(e for e in current["events"] if e["id"] == row["eventId"])
    preview.require(next((e for e in before["events"] if e["id"] == old["id"]), None) == old,
                    "Pending batch independently changes corrected event")
    expected_events = [contract.expected(e, plan) if e["id"] == old["id"] else e
                       for e in before["events"]]
    # Publisher applies lineup corrections before admitting pending events.
    # The real baseline can remove separately authorized orphan IDs.
    # Only its exact receipts may explain missing historical identities.
    retired = set(before.get("retiredArtistIds", []))
    old_artists = [a for a in current["artists"] if a["id"] not in retired]
    n = len(old_artists)
    preview.require(before["artists"][:n] == old_artists,
                    "Pending batch modifies historical artist identities")
    expected_artists = (before["artists"][:n] + plan["newArtists"] +
                        before["artists"][n:])
    expected_counts = dict(before_counts)
    expected_counts["correctedEvents"] += 1
    expected_counts["newArtists"] += len(plan["newArtists"])
    preview.require(after["events"] == expected_events
                    and after["artists"] == expected_artists
                    and after["venues"] == before["venues"]
                    and after_counts == expected_counts,
                    "Correction alters independently validated pending publication")
    ignored = {"events", "artists", "venues", "updatedAt", "edition"}
    preview.require({k: v for k, v in before.items() if k not in ignored} ==
                    {k: v for k, v in after.items() if k not in ignored},
                    "Unrelated catalogue metadata modified")
    return 1


def select(previous, report, reference, current, today, *, audit=audit_correction):
    """Return an unchanged or one-row-extended ledger and private diagnostics."""
    result = {"status": "no_changes", "validatedByPublisher": False,
              "applied": False, "examined": 0, "held": 0}
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("asOf") != today.isoformat()
            or report.get("publicationAllowed") is not False
            or report.get("publisherAuthorityGranted") is not False
            or not isinstance(report.get("proposals"), list)):
        result["status"] = "invalid_or_stale_proposals"
        return previous, result
    if (not isinstance(previous, dict)
            or previous.get("schema") != "grossesondes.concert.approvals.v1"
            or not isinstance(previous.get("approvals"), list)
            or not isinstance(previous.get("lineupCorrections", []), list)):
        raise ValueError("Invalid private approval ledger")
    events = {e["id"]: e for e in current["events"]}
    approvals = {a["event"]["id"]: a for a in previous["approvals"]}
    if len(approvals) != len(previous["approvals"]):
        raise ValueError("Duplicate historical approval ID")
    old = previous.get("lineupCorrections", [])
    corrected = {r["eventId"] for r in old}
    if len(corrected) != len(old):
        raise ValueError("Duplicate historical correction ID")
    for row in old:
        e = events.get(row["eventId"], {})
        if (e.get("artistIds") != row.get("artistIds")
                or e.get("title") != row.get("title")):
            result["status"] = "deferred_previous_correction_pending"
            return previous, result
    protected = {e["id"] for e in reference["events"]}
    seen = set()
    for row in report["proposals"]:
        if not isinstance(row, dict):
            continue
        evidence = row.get("officialEvidence")
        if (not isinstance(evidence, list) or len(evidence) != 1
                or not isinstance(evidence[0], dict)
                or evidence[0].get("proofType") not in (contract.PROMOTIONAL_PROOF,
                    contract.bill_identity.PROOF)):
            continue
        eid = row.get("eventId")
        if (not isinstance(eid, str) or eid in seen or eid in corrected
                or eid in protected or eid not in approvals
                or eid not in events):
            continue
        if result["examined"] >= 8:
            break
        seen.add(eid)
        result["examined"] += 1
        if row.get("reviewedAt") != today.isoformat():
            result["held"] += 1
            continue
        proposed = copy.deepcopy(previous)
        proposed.setdefault("lineupCorrections", []).append(copy.deepcopy(row))
        try:
            contract.plan(row, approvals[eid], current, today)
            # Real publisher re-fetches the UID-bound source independently,
            # checks historical protections and the exact event/artist delta.
            if audit(previous, proposed, reference, current, today) != 1:
                raise ValueError("Unexpected private correction preview delta")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError) as exc:
            result["held"] += 1
            # Private-only diagnostic; no HTML, URLs or proof payloads.
            result.setdefault("heldDiagnostics", []).append({
                "eventId": eid, "reason": str(exc).split("\n", 1)[0][:160]})
            continue
        result["status"] = "validated"
        result["validatedByPublisher"] = True
        return proposed, result
    if result["held"]:
        result["status"] = "held"
    return previous, result


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "proposals", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    original = load(args.before)
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    proposed, result = select(original, load(args.proposals),
                              load(args.reference), load(args.catalogue), today)
    if args.apply and result["validatedByPublisher"]:
        atomic_store(args.before, proposed)
        result["applied"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Promotional correction preflight complete; see private report.")


if __name__ == "__main__":
    main()
