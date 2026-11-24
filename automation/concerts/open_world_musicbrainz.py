#!/usr/bin/env python3
"""MusicBrainz name-to-identity discovery: private hypotheses, never proof.

Only the public artist name is queried, never registry IDs, venues or events.
The fixed HTTPS API is rate limited, redirects and proxies disabled. Community
genres and official-homepage relations are navigation hints, not authority.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import (build_opener, HTTPRedirectHandler, ProxyHandler,
                            Request)
from zoneinfo import ZoneInfo

import artist_genre_knowledge as knowledge
import open_world_frontier as frontier

SCHEMA = "grossesondes.concert.musicbrainz-research.v1"
BASE = "https://musicbrainz.org/ws/2/artist/"
AGENT = "GrossesOndes-Concerts/1.0 (https://grosses-ondes.fr/)"
MAX_NAMES = 12
MAX_BYTES = 400_000
SEARCH_LIMIT = 20


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.last = None

    def __call__(self, path, params):
        if path and not valid_id(path):
            raise ValueError("Invalid MusicBrainz ID")
        if self.last is not None:
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        url = BASE + path + "?" + urlencode(dict(params, fmt="json"))
        req = Request(url, headers={"User-Agent": AGENT,
                                   "Accept": "application/json",
                                   "Accept-Encoding": "identity"})
        with self.opener.open(req, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("MusicBrainz response too large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid MusicBrainz object")
        return data


def valid_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def exact(value):
    return (unicodedata.normalize("NFKC", value).strip().casefold()
            if isinstance(value, str) else "")


def candidate_names(registry, today):
    if (not isinstance(registry, dict)
            or registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)):
        raise ValueError("Invalid private registry")
    names = {}
    for record in registry["items"].values():
        if not isinstance(record, dict) or record.get("status") != "pending_review":
            continue
        lead = record.get("candidate")
        if (not isinstance(lead, dict)
                or lead.get("publicationAllowed") is not False
                or lead.get("reviewRequired") is not True
                or lead.get("cancellationNotice") is True):
            continue
        try:
            if dt.date.fromisoformat(lead.get("date")) < today:
                continue
        except (TypeError, ValueError):
            continue
        for name in frontier.observed_artists(lead):
            names.setdefault(exact(name), name)
    return names


def research(name, request):
    # Literal phrase; never let artist text inject Lucene operators.
    phrase = name.replace("\\", "\\\\").replace('"', '\\"')
    search = request("", {"query": 'artist:"' + phrase + '"',
                          "limit": SEARCH_LIMIT})
    rows, count = search.get("artists"), search.get("count")
    if (not isinstance(rows, list) or type(count) is not int
            or count < 0 or count < len(rows)):
        raise ValueError("Malformed artist search")
    if count > len(rows):
        return {"status": "ambiguous_or_incomplete"}
    matches = [x for x in rows if isinstance(x, dict)
               and exact(x.get("name")) == exact(name)]
    if len(matches) != 1:
        return {"status": "ambiguous_or_incomplete" if matches else "not_found"}
    candidate = matches[0]
    mbid = candidate.get("id")
    if not valid_id(mbid):
        raise ValueError("Malformed artist identity")
    detail = request(mbid, {"inc": "url-rels+genres"})
    if (detail.get("id") != mbid or exact(detail.get("name")) != exact(name)
            or detail.get("type") not in {"Group", "Person", "Orchestra", "Choir"}):
        return {"status": "identity_held"}
    genres = knowledge._genre_labels([
        x.get("name") for x in detail.get("genres", [])
        if isinstance(x, dict) and isinstance(x.get("name"), str)
        and type(x.get("count")) is int and x["count"] > 0
    ])
    links = set()
    for row in detail.get("relations", []):
        if (not isinstance(row, dict) or row.get("type") != "official homepage"
                or row.get("target-type") != "url" or row.get("ended") is True):
            continue
        target = row.get("url")
        target = target.get("resource") if isinstance(target, dict) else None
        if not isinstance(target, str) or not target.startswith("https://"):
            continue
        parts = urlsplit(target)
        if not parts.hostname or parts.username or parts.password or parts.fragment:
            continue
        if not parts.path:
            target = parts._replace(path="/").geturl()
        links.add(target)
    return {"status": "hypothesis", "mbid": mbid, "genres": genres,
            "homepageHints": sorted(links), "artistType": detail["type"]}


def build(registry, today, *, prior=None, limit=MAX_NAMES, request=None):
    if type(limit) is not int or not 1 <= limit <= MAX_NAMES:
        raise ValueError("Invalid MusicBrainz budget")
    if prior is None:
        prior = {"schema": SCHEMA, "publicationAllowed": False, "entries": {}}
    if (not isinstance(prior, dict) or prior.get("schema") != SCHEMA
            or prior.get("publicationAllowed") is not False
            or not isinstance(prior.get("entries"), dict)):
        raise ValueError("Untrusted MusicBrainz memory")
    entries = dict(prior["entries"])
    names = candidate_names(registry, today)
    eligible = []
    for key, name in names.items():
        entry = entries.get(key, {})
        try:
            age = (today - dt.date.fromisoformat(entry["checkedAt"])).days
        except (TypeError, KeyError, ValueError):
            age = 99999
        if age >= (30 if entry.get("status") == "hypothesis" else 7):
            eligible.append((-age, key, name))
    counters = Counter()
    request = request if request is not None else Client()
    checked = 0
    for _, key, name in sorted(eligible)[:limit]:
        checked += 1
        try:
            result = research(name, request)
        except (ValueError, TypeError, OSError, TimeoutError, KeyError):
            # Stop on service failure or rate limiting; keep prior memory.
            counters["serviceHeld"] += 1
            break
        entries[key] = dict(result, artistName=name, checkedAt=today.isoformat(),
                            identityVerified=False, publicationAllowed=False)
        counters[result["status"]] += 1
    return {"schema": SCHEMA, "asOf": today.isoformat(),
            "publicationAllowed": False, "approvalsProposed": 0,
            "eligibleNames": len(names), "dueNames": len(eligible),
            "namesChecked": checked, "reasonCounts": dict(counters),
            "entries": entries}


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
    print("MusicBrainz private research:", result["namesChecked"],
          "names checked; zero approvals.")


if __name__ == "__main__":
    main()
