#!/usr/bin/env python3
"""Build private signed-lineup *proposals* from nationwide live completeness audit.

All official event URLs are discoveries, never a publisher authority grant.
This module never mutates approvals or the public catalogue; the separately
trusted publisher makes its OWN fresh HTTPS recheck before applying any patch.
No venue, artist, host, subgenre or HTML template whitelist is used here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automation.concerts import published_lineup_audit as audit
from automation.concerts import source_evidence_probe as probe
from scripts import concert_published_lineup_contract as contract

SCHEMA = "grossesondes.concert.published-lineup-patch-proposals.v1"


def require(ok, reason):
    if not ok:
        raise ValueError("Published lineup proposal: " + reason)


def _identity(name, known, pending):
    """Resolve a published name/alias, otherwise create ONE unclassified band."""
    key = contract.normal(name)
    require(key and 2 <= len(name.strip()) <= 120, "empty official artist name")
    hits = []
    for artist in list(known.values()) + list(pending.values()):
        aliases = [artist.get("name")] + list(artist.get("aliases") or [])
        if key in {contract.normal(x) for x in aliases if isinstance(x, str)}:
            hits.append(artist["id"])
    require(len(hits) <= 1, "ambiguous existing artist name or alias")
    if hits:
        return hits[0]
    slug = key.replace(" ", "-")[:100].strip("-")
    require(bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug))
            and slug not in known and slug not in pending,
            "artist ID collision; manual disambiguation required")
    pending[slug] = {"id": slug, "name": name, "aliases": []}
    return slug


def build(catalogue, observed, today, *, fetch=probe.safe_fetch):
    """Only freshly, individually verified missing lineups may become proposals.

    Rotation/cost controls are owned by the read-only scanner; no total number
    of artists is limited here. An audit report alone never authorizes a patch.
    """
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and isinstance(catalogue.get("events"), list)
            and isinstance(catalogue.get("venues"), list)
            and isinstance(catalogue.get("artists"), list),
            "invalid public catalogue")
    require(isinstance(observed, dict) and observed.get("schema") == audit.SCHEMA
            and isinstance(observed.get("checks"), list)
            and observed.get("publicationAllowed") is False
            and isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "untrusted audit report")
    events = {row["id"]: row for row in catalogue["events"]}
    venues = {row["id"]: row for row in catalogue["venues"]}
    artists = {row["id"]: row for row in catalogue["artists"]}
    cache, seen, proposals, held, counts = {}, set(), [], [], Counter()
    for row in observed["checks"]:
        event_id = row.get("eventId") if isinstance(row, dict) else None
        if not isinstance(event_id, str) or event_id in seen:
            held.append({"eventId": event_id, "reason": "invalid_or_duplicate_id"})
            continue
        seen.add(event_id)
        if row.get("state") != "published_lineup_incomplete":
            counts["not_a_verified_missing_lineup"] += 1
            continue
        event = events.get(event_id)
        try:
            require(event is not None and event["date"] >= today.isoformat()
                    and event.get("status") == "confirmed"
                    and event.get("officialUrl") == row.get("officialUrl")
                    and row.get("officialBillRechecked") is True,
                    "event, URL or official audit state changed")
            html = fetch(event["officialUrl"], cache)
            bill = audit.bill_from_page(html, event, venues.get(event["venueId"]),
                                        artists)
            names = bill["officialNames"]
            require(bool(bill["missingNamedArtists"]), "already complete")
            known = {a["id"]: a for a in catalogue["artists"]}
            pending = {}
            ids = [_identity(name, known, pending) for name in names]
            require(len(ids) == len(set(ids)), "same artist shown twice")
            require(all(original in ids for original in event["artistIds"]),
                    "official page omits an already published artist")
            require(len(ids) > len(event["artistIds"]),
                    "no net addition; do not remove artists automatically")
            # Keep the order supplied by the official bill, not a sorted set.
            title = " + ".join(names)
            proposal = {
                "eventId": event_id, "reviewDecision": "approved",
                "reviewedBy": "automated-official-recheck",
                "reviewedAt": today.isoformat(),
                "date": event["date"], "venueId": event["venueId"],
                "officialUrl": event["officialUrl"],
                "oldArtistIds": list(event["artistIds"]),
                "artistIds": ids, "title": title,
                "newArtists": list(pending.values()),
                "officialEvidence": [{
                    "url": event["officialUrl"],
                    "proofType": "official-published-lineup-v1",
                    "checkedAt": today.isoformat(),
                    "checkedFields": ["artists", "date", "venue"],
                    "confirmedArtists": names,
                }],
            }
            # Even the proposal must satisfy the independent publisher's
            # strict envelope before entering the private append-only queue.
            contract.plan(proposal, {"reviewDecision": "approved",
                                     "event": {k: event[k] for k in
                                         ("id", "title", "date", "artistIds",
                                          "venueId", "genres", "status",
                                          "officialUrl", "sourceType")}},
                          catalogue, today)
            proposals.append(proposal)
            counts["proposed"] += 1
        except (KeyError, ValueError, TypeError, OSError, TimeoutError) as error:
            # Reason category only, never log private official HTML.
            held.append({"eventId": event_id,
                         "reason": "not_sufficiently_corroborrated"})
            counts["held"] += 1
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "proposals": proposals, "held": held,
        "stateCounts": dict(sorted(counts.items())),
        "publisherAuthorityGranted": False, "publicationAllowed": False,
    }


def build_promotional(catalogue, approved, today, *, fetch=probe.safe_fetch, limit=8):
    """Find published promotional names from the original signed OA ledger.

    Only propose corrections, never modify either input. Network work is
    bounded by event count, not artist count. Already signed or corrected
    events are skipped; future runs retry an unproven candidate.
    """
    from automation.concerts import openagenda_official_concert as oa
    from scripts import concert_openagenda_bill_identity as identity
    require(isinstance(approved, dict)
            and approved.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(approved.get("approvals"), list)
            and isinstance(approved.get("lineupCorrections", []), list)
            and type(limit) is int and 0 <= limit <= 8,
            "invalid signed approval ledger or review budget")
    events = {e["id"]: e for e in catalogue["events"]}
    known = {a["id"]: a for a in catalogue["artists"]}
    corrected = {r["eventId"] for r in approved.get("lineupCorrections", [])}
    seen, cache, proposals, held = set(), {}, [], []
    for original in approved["approvals"]:
        event = original.get("event") or {}
        eid = event.get("id")
        current = events.get(eid)
        if (eid in corrected or eid in seen or current is None
                or current.get("status") != "confirmed"
                or current.get("date", "") < today.isoformat()
                or current.get("artistIds") != event.get("artistIds")
                or current.get("title") != event.get("title")
                or not any(oa.promotional_artist_candidate(known.get(aid, {}).get("name"))
                           or identity.possible(known.get(aid, {}).get("name"))
                           for aid in current.get("artistIds", []))):
            continue
        if len(proposals) + len(held) >= limit:
            break
        seen.add(eid)
        try:
            require(all(current.get(k) == event.get(k) for k in
                        ("id", "date", "venueId", "officialUrl", "genres",
                         "status", "sourceType")),
                    "published event identity differs from original approval")
            repaired = any(identity.possible(known.get(aid, {}).get("name"))
                           for aid in current["artistIds"])
            if repaired:
                names = identity.recheck(original, catalogue, fetch=lambda url: fetch(url, cache))
            else:
                names = contract.recheck_promotional(
                    original, catalogue, fetch=lambda url: fetch(url, cache))
            pending = {}
            ids = [_identity(name, known, pending) for name in names]
            row = {
                "eventId": eid, "reviewDecision": "approved",
                "reviewedBy": "automated-official-recheck",
                "reviewedAt": today.isoformat(),
                "date": event["date"], "venueId": event["venueId"],
                "officialUrl": event["officialUrl"],
                "oldArtistIds": list(event["artistIds"]), "artistIds": ids,
                "title": " + ".join(names), "newArtists": list(pending.values()),
                "officialEvidence": [{
                    "url": event["officialUrl"], "proofType": identity.PROOF if repaired else contract.PROMOTIONAL_PROOF,
                    "checkedAt": today.isoformat(),
                    "checkedFields": ["artists", "date", "venue"],
                    "confirmedArtists": names,
                }],
            }
            contract.plan(row, original, catalogue, today)
            proposals.append(row)
        except (KeyError, ValueError, TypeError, OSError, TimeoutError):
            held.append({"eventId": eid, "reason": "promotional_identity_unproven"})
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "proposals": proposals, "held": held,
        "stateCounts": {"promotional_identity_proposed": len(proposals),
                        "promotional_identity_held": len(held)},
        "publisherAuthorityGranted": False, "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--approved", help="Original append-only signed private ledger")
    args = parser.parse_args()
    cat = json.loads(Path(args.catalogue).read_text(encoding="utf-8"))
    report = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    doc = build(cat, report, today)
    if args.approved:
        ledger = json.loads(Path(args.approved).read_text(encoding="utf-8"))
        identity = build_promotional(cat, ledger, today)
        already = {row["eventId"] for row in doc["proposals"]}
        doc["proposals"].extend(
            row for row in identity["proposals"] if row["eventId"] not in already)
        doc["held"].extend(identity["held"])
        doc["stateCounts"].update(identity["stateCounts"])
    Path(args.output).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Lineup patch proposals prepared privately; no publication.")


if __name__ == "__main__":
    main()
