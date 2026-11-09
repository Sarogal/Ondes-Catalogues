#!/usr/bin/env python3
"""Archive append-only des trouvailles concert dans le dépôt PRIVE GrossesOndes.

Les candidats restent en attente de vérification; ne publie JAMAIS de JSON public.
Tous les états et l'historique des corrections sont conservés par Git.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

SCHEMA = "grossesondes.concert.intake.v1"
DISCOVERY_SCHEMA = "grossesondes.concert.discovery.v1"

# Only stable first-party identity fields may count as repeated evidence.
# A changed date, venue, bill, genre or duplicate flag starts a NEW streak.
IDENTITY_FIELDS = (
    "source", "sourceUrl", "date", "name", "leadArtist", "venue", "city",
    "department", "venueCatalogueId", "classification", "reviewBucket",
    "possibleExistingConcert", "officialDetailFound", "genreToConfirm",
)


def identity_signature(candidate):
    """Canonical identity for repeat-observation stability, not proof itself."""
    return json.dumps(
        {field: candidate.get(field) for field in IDENTITY_FIELDS},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def observation_day(timestamp):
    try:
        return dt.date.fromisoformat(str(timestamp)[:10]).isoformat()
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid observation date") from exc



def merge(previous, discovery, now):
    if discovery.get("schema") != DISCOVERY_SCHEMA:
        raise ValueError("Rapport de découverte inconnu")
    items = discovery.get("candidates")
    if not isinstance(items, list):
        raise ValueError("Propositions absentes")
    counts = discovery.get("triageCounts", {})
    if not isinstance(counts, dict) or sum(counts.values()) != len(items):
        raise ValueError("Liste tronquée ou compte de propositions incohérent")
    if not previous:
        registry = {"schema": SCHEMA, "version": 1,
                    "description": "Registre privé cumulatif — aucune publication",
                    "items": {}}
    else:
        registry = json.loads(json.dumps(previous))
        if registry.get("schema") != SCHEMA:
            raise ValueError("Registre privé inattendu")
    entries = registry.get("items")
    if not isinstance(entries, dict):
        raise ValueError("Registre invalide")
    seen = set()
    added = 0
    updated = 0
    stable_reobserved = 0
    restarted_stability = 0
    day = observation_day(now)
    for candidate in items:
        cid = candidate.get("candidateId")
        if not isinstance(cid, str) or not cid or len(cid) > 240 or cid in seen:
            raise ValueError("ID manquant ou dupliqué dans le lot")
        seen.add(cid)
        if candidate.get("publicationAllowed") is not False or candidate.get("reviewRequired") is not True:
            raise ValueError("Candidat pas explicitement en quarantaine")
        if candidate.get("sourceUrl") and not candidate["sourceUrl"].startswith("https://"):
            raise ValueError("URL de source non HTTPS")
        if not isinstance(candidate.get("name"), str) or not candidate.get("name"):
            raise ValueError("Nom vide")
        if cid not in entries:
            entries[cid] = {
                "candidateId": cid, "status": "pending_review",
                "firstSeenAt": now, "lastSeenAt": now,
                "observations": 1, "candidate": candidate,
                "stableObservations": 1,
                "lastStableObservationDay": day,
                "identitySignature": identity_signature(candidate),
            }
            added += 1
        else:
            record = entries[cid]
            if record.get("status") not in ("pending_review", "approved", "rejected", "superseded"):
                raise ValueError("Statut existant inconnu : " + cid)
            if not record.get("firstSeenAt"):
                raise ValueError("FirstSeen absent")
            # Ne réactive PAS un candidat rejeté et n'efface pas la décision.
            signature = identity_signature(candidate)
            if record.get("identitySignature") != signature:
                # Conservative migration for historical rows: do not claim
                # earlier observations were independent or identity-stable.
                record["identitySignature"] = signature
                record["stableObservations"] = 1
                record["lastStableObservationDay"] = day
                restarted_stability += 1
            elif record.get("lastStableObservationDay") != day:
                record["stableObservations"] = int(
                    record.get("stableObservations", 0)) + 1
                record["lastStableObservationDay"] = day
                stable_reobserved += 1
            record["lastSeenAt"] = now
            record["observations"] = int(record.get("observations", 0)) + 1
            record["candidate"] = candidate
            updated += 1
    registry["lastRunAt"] = now
    registry["lastRunCandidates"] = len(items)
    registry["total"] = len(entries)
    return registry, {"added": added, "seenAgain": updated, "total": len(entries),
                      "stableReobservedOnNewDay": stable_reobserved,
                      "stabilityResetOrMigrated": restarted_stability,
                      "stableEligible": sum(
                          r.get("status") == "pending_review"
                          and r.get("stableObservations", 0) >= 2
                          for r in entries.values())}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--store", required=True)
    p.add_argument("--summary", required=True)
    args = p.parse_args()
    discovery = json.loads(pathlib.Path(args.source).read_text(encoding="utf-8"))
    store = pathlib.Path(args.store)
    prev = json.loads(store.read_text(encoding="utf-8")) if store.exists() else None
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    archive, result = merge(prev, discovery, now)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(archive, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                     encoding="utf-8")
    pathlib.Path(args.summary).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print("Archive privée:", result)


if __name__ == "__main__":
    sys.exit(main())
