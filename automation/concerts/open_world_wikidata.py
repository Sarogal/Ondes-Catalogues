#!/usr/bin/env python3
"""Independent bounded artist-homepage discovery; never publication evidence.

Only public performer names reach the fixed Wikidata API. Directory identities
and websites are untrusted navigation hints; no community genre is imported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, ProxyHandler, Request
from zoneinfo import ZoneInfo

import open_world_musicbrainz as mb
import source_admission_intake as intake

SCHEMA = "grossesondes.concert.wikidata-research.v1"
BASE = "https://www.wikidata.org/w/api.php"
MAX_NAMES = 12
MAX_BYTES = 600_000
SEARCH_LIMIT = 20
MAX_EXACT_MATCHES = 6
# Only explicit non-performer classes can eliminate an exact-name collision.
# Unknown types, humans without musical claims, and incomplete data stay held.
NON_PERFORMER_TYPES = frozenset({"Q4167410", "Q11424", "Q482994", "Q7366"})


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"Q[1-9][0-9]{0,15}", value))


class Client:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), mb.NoRedirect())
        self.last = None

    def __call__(self, params):
        if self.last is not None:
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        req = Request(BASE + "?" + urlencode(dict(params, format="json", maxlag=5)),
                      headers={"User-Agent": mb.AGENT, "Accept": "application/json",
                               "Accept-Encoding": "identity"})
        with self.opener.open(req, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Oversized directory response")
        data = json.loads(raw)
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Directory unavailable")
        return data


def claims(entity, prop):
    rows = entity.get("claims", {}).get(prop, [])
    if not isinstance(rows, list) or len(rows) > 100:
        return []
    values = []
    for row in rows:
        if not isinstance(row, dict) or row.get("rank") == "deprecated":
            continue
        snak = row.get("mainsnak") or {}
        value = (snak.get("datavalue") or {}).get("value")
        if snak.get("snaktype") == "value":
            values.append(value)
    return values


def ids(entity, prop):
    return {v["id"] for v in claims(entity, prop)
            if isinstance(v, dict) and valid_id(v.get("id"))}


def research(name, request):
    # Search both languages; do not pick the top hit or silently resolve
    # homonyms. A continued result set is incomplete, not a unique identity.
    matches = set()
    for lang in ("fr", "en"):
        data = request({"action": "wbsearchentities", "search": name,
                        "language": lang, "type": "item", "limit": SEARCH_LIMIT})
        if "search-continue" in data or "continue" in data:
            return {"status": "ambiguous_or_incomplete"}
        rows = data.get("search")
        if not isinstance(rows, list) or len(rows) >= SEARCH_LIMIT:
            return {"status": "ambiguous_or_incomplete"}
        for row in rows:
            if not isinstance(row, dict):
                continue
            match = row.get("match") or {}
            if mb.exact(row.get("label")) == mb.exact(name) or (
                    isinstance(match, dict) and mb.exact(match.get("text")) == mb.exact(name)):
                if not valid_id(row.get("id")):
                    raise ValueError("Malformed identity")
                matches.add(row["id"])
    if not matches:
        return {"status": "not_found"}
    if len(matches) > MAX_EXACT_MATCHES:
        return {"status": "ambiguous_or_incomplete"}
    data = request({"action": "wbgetentities", "ids": "|".join(sorted(matches)),
                    "props": "labels|aliases|claims", "languages": "fr|en"})
    entities = data.get("entities")
    if not isinstance(entities, dict):
        return {"status": "identity_held"}
    musicians = []
    unresolved = False
    for qid in sorted(matches):
        entity = entities.get(qid)
        if not isinstance(entity, dict) or entity.get("id") != qid:
            unresolved = True
            continue
        labels = [v.get("value") for v in entity.get("labels", {}).values()
                  if isinstance(v, dict)]
        for rows in entity.get("aliases", {}).values():
            if isinstance(rows, list):
                labels.extend(v.get("value") for v in rows if isinstance(v, dict))
        if mb.exact(name) not in {mb.exact(v) for v in labels}:
            unresolved = True
            continue
        kinds = ids(entity, "P31")
        musical = ("Q215380" in kinds or ("Q5" in kinds and
                   (ids(entity, "P106") & {"Q639669", "Q177220", "Q488205", "Q753110"}
                    or ids(entity, "P136"))))
        if musical:
            musicians.append((qid, entity))
        elif not kinds or not kinds <= NON_PERFORMER_TYPES:
            # A sparse or unfamiliar taxonomy is NOT negative evidence.
            unresolved = True
    if len(musicians) != 1 or unresolved:
        return {"status": "ambiguous_or_incomplete" if len(matches) > 1 else "identity_held"}
    qid, entity = musicians[0]
    # This is still just an unverified navigation hint; no artist identity
    # or event genre is authenticated by filtering directory homonyms.
    links = set()
    for value in claims(entity, "P856"):
        if not isinstance(value, str) or len(value) > 1000:
            continue
        if "\r" in value or "\n" in value or not intake.valid_https(value):
            continue
        parsed = urlsplit(value)
        links.add(parsed._replace(path=parsed.path or "/").geturl())
    return {"status": "hypothesis", "qid": qid, "homepageHints": sorted(links)}


def build(registry, today, *, prior=None, limit=MAX_NAMES, request=None):
    if type(limit) is not int or not 1 <= limit <= MAX_NAMES:
        raise ValueError("Invalid directory budget")
    if prior is None:
        prior = {"schema": SCHEMA, "publicationAllowed": False,
                 "approvalsProposed": 0, "entries": {}}
    if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or prior.get("approvalsProposed") != 0
            or not isinstance(prior.get("entries"), dict)):
        raise ValueError("Invalid directory memory")
    entries = dict(prior["entries"])
    names = mb.candidate_tasks(registry, today)
    due = []
    for key, (priority, day, name) in names.items():
        entry = entries.get(key, {})
        try:
            age = (today - dt.date.fromisoformat(entry["checkedAt"])).days
        except (KeyError, TypeError, ValueError):
            age = 99999
        if age >= (30 if entry.get("status") == "hypothesis" else 7):
            due.append((-age, priority, day, key, name))
    ordered = sorted(due)
    cursor = prior.get("serviceRetryAfterKey")
    for i, row in enumerate(ordered):
        if row[3] == cursor:
            ordered = ordered[i + 1:] + ordered[:i + 1]
            break
    request = request if request is not None else Client()
    counters, checked, failure, retry = Counter(), 0, None, None
    for _, _, _, key, name in ordered[:limit]:
        checked += 1
        try:
            result = research(name, request)
        except (ValueError, TypeError, AttributeError, KeyError, OSError, TimeoutError) as exc:
            counters["serviceHeld"] += 1
            failure, retry = mb.service_failure_kind(exc), key
            break
        entries[key] = dict(result, artistName=name, checkedAt=today.isoformat(),
                            identityVerified=False, publicationAllowed=False)
        counters[result["status"]] += 1
    return {"schema": SCHEMA, "asOf": today.isoformat(),
            "publicationAllowed": False, "approvalsProposed": 0,
            "eligibleNames": len(names), "dueNames": len(due),
            "namesChecked": checked, "reasonCounts": dict(counters),
            "entries": entries, "serviceFailureKind": failure,
            "serviceRetryAfterKey": retry}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    result = build(json.loads(args.registry.read_text("utf-8")), today,
                   prior=json.loads(args.out.read_text("utf-8"))
                   if args.out.exists() else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", "utf-8")
    tmp.replace(args.out)
    print("Wikidata private research:", result["namesChecked"], "names checked; zero approvals.")


if __name__ == "__main__":
    main()
