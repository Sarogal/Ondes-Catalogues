#!/usr/bin/env python3
"""MusicBrainz research for observed radio artists; hypotheses, not admission."""
import argparse
import datetime as dt
import json
import re
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

from radio_daily_metadata_preview import valid_hint
from radio_daily_qualification_dossiers import index
from radio_stream_recheck_ledger import parse_day, SHA256_RE

BASE = "https://musicbrainz.org/ws/2/artist/"
SOURCE = "musicbrainz"
MAX_NAMES = 8
MAX_BYTES = 400_000
MAX_STATE = 12 * 1024 * 1024
SEARCH_LIMIT = 25

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def valid_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False

def key(name):
    return unicodedata.normalize("NFC", name).strip().lower()

def safe_name(name):
    return (isinstance(name, str) and 2 <= len(name) <= 100
            and any(c.isalpha() for c in name)
            and not any(unicodedata.category(c).startswith("C") for c in name)
            and not re.search(r"https?://|www\.|@|[?=]", name, re.I))

class Client:
    """Fixed HTTPS origin, no redirects/proxies, sequential rate-limited requests."""
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.last = None

    def __call__(self, path, params):
        return self._request(BASE, path, params)

    def recordings(self, params):
        return self._request("https://musicbrainz.org/ws/2/recording/", "", params)

    def _request(self, base, path, params):
        if path and not valid_id(path):
            raise ValueError("invalid MBID")
        if self.last is not None:
            time.sleep(max(0, 1.2 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        req = Request(base + path + "?" + urlencode(dict(params, fmt="json")),
                      headers={"User-Agent": "GrossesOndes-RadioPreview/1.0 (https://grosses-ondes.fr/)",
                               "Accept": "application/json", "Accept-Encoding": "identity"})
        with self.opener.open(req, timeout=8) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("oversize response")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        return data

def research(name, request):
    # Literal Lucene phrase; untrusted metadata is never query syntax.
    phrase = name.replace("\\", "\\\\").replace('"', '\\"')
    result = request("", {"query": 'artist:"' + phrase + '"', "limit": SEARCH_LIMIT})
    rows, count = result.get("artists"), result.get("count")
    if not isinstance(rows, list) or type(count) is not int or count < len(rows):
        raise ValueError("invalid search result")
    if count > len(rows):
        return {"status": "ambiguous_or_incomplete"}
    matches = [x for x in rows if isinstance(x, dict) and isinstance(x.get("name"), str)
               and key(x["name"]) == key(name)]
    if len(matches) != 1:
        return {"status": "ambiguous_or_incomplete" if matches else "not_found"}
    mbid = matches[0].get("id")
    if not valid_id(mbid):
        raise ValueError("invalid artist id")
    detail = request(mbid, {"inc": "genres"})
    if (detail.get("id") != mbid or not isinstance(detail.get("name"), str)
            or key(detail["name"]) != key(name)):
        return {"status": "identity_held"}
    genres = detail.get("genres", [])
    if not isinstance(genres, list) or len(genres) > 200:
        raise ValueError("invalid genre list")
    # Keep all documented genres, including outside the GO editorial universe.
    labels = sorted({g["name"].strip() for g in genres
                     if isinstance(g, dict) and safe_name(g.get("name"))
                     and type(g.get("count")) is int and g["count"] > 0})
    return {"status": "name_hypothesis", "mbid": mbid,
            "genres": labels, "genreSource": "musicbrainz-community",
            "sourceUrl": "https://musicbrainz.org/artist/" + mbid}

def build(metadata, *, prior=None, limit=0, request=None):
    day = parse_day(metadata["scanDate"])
    if (metadata.get("schemaVersion") != 1 or metadata.get("publicationAllowed") is not False
            or metadata.get("approvedCount") != 0 or type(limit) is not int
            or not 0 <= limit <= MAX_NAMES):
        raise ValueError("untrusted metadata or budget")
    names = {}
    for row in index(metadata, "records").values():
        if (row.get("approved") is not False or row.get("publicationAllowed") is not False
                or not SHA256_RE.fullmatch(row.get("streamSha256") or "")
                or parse_day(row["observedDate"]) > day
                or not isinstance(row.get("observations"), list) or len(row["observations"]) > 90):
            raise ValueError("untrusted metadata row")
        for obs in row["observations"]:
            if not valid_hint(obs) or parse_day(obs["date"]) > day:
                raise ValueError("untrusted observation")
            name = obs["artistHint"].strip()
            if safe_name(name):
                names.setdefault(key(name), set()).add(name)
    entries = {}
    if prior is not None:
        if (prior.get("schemaVersion") != 1 or prior.get("publicationAllowed") is not False
                or prior.get("approvedCount") != 0 or parse_day(prior["scanDate"]) > day
                or not isinstance(prior.get("entries"), dict)):
            raise ValueError("untrusted artist cache")
        for k, entry in prior["entries"].items():
            if (not isinstance(entry, dict) or not safe_name(entry.get("artistName"))
                    or key(entry["artistName"]) != k or entry.get("identityVerified") is not False
                    or entry.get("publicationAllowed") is not False
                    or entry.get("source") != SOURCE or parse_day(entry["checkedAt"]) > day):
                raise ValueError("untrusted cache entry")
            entries[k] = entry
    today = dt.date.fromisoformat(day)
    tasks = []
    for k, spellings in names.items():
        # Different spellings sharing a normalized key are held, not merged.
        if len(spellings) != 1:
            continue
        old = entries.get(k)
        age = (today - dt.date.fromisoformat(old["checkedAt"])).days if old else 999999
        ttl = 30 if old and old.get("status") == "name_hypothesis" and old.get("genres") else 7
        if age >= ttl:
            tasks.append((-age, k, next(iter(spellings))))
    tasks.sort()
    cursor = prior.get("retryAfterKey") if prior else None
    if cursor:
        for i, (_, k, _) in enumerate(tasks):
            if k == cursor:
                tasks = tasks[i+1:] + tasks[:i+1]
                break
    attempted = 0
    failure = None
    retry = None
    if limit and request is None:
        request = Client()
    for _, k, name in tasks[:limit]:
        attempted += 1
        try:
            result = research(name, request)
        except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
            # Bounded diagnostics: never persist exception strings or request URLs.
            if isinstance(exc, HTTPError):
                failure = "http_" + str(exc.code)
            elif isinstance(exc, TimeoutError) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)):
                failure = "timeout"
            elif isinstance(exc, OSError):
                failure = "network_error"
            else:
                failure = "invalid_response"
            retry = k
            break
        entries[k] = dict(result, artistName=name, source=SOURCE, checkedAt=day,
                          identityVerified=False, publicationAllowed=False)
    return {"schemaVersion": 1, "scanDate": day, "publicationAllowed": False,
            "approvedCount": 0, "observedNameCount": len(names), "dueNameCount": len(tasks),
            "attemptedCount": attempted, "serviceFailure": failure, "retryAfterKey": retry,
            "entries": dict(sorted(entries.items()))}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metadata", required=True, type=Path)
    p.add_argument("--previous", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--allow-network", action="store_true")
    args = p.parse_args()
    if args.limit and not args.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size > MAX_STATE:
            raise ValueError("oversize input")
        return json.loads(path.read_text("utf-8"))
    result = build(load(args.metadata), prior=load(args.previous) if args.previous else None,
                   limit=args.limit)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if len(payload.encode()) > MAX_STATE:
        raise ValueError("oversize artist cache")
    args.output.write_text(payload, encoding="utf-8")
    print("RADIO_ARTIST_RESEARCH_PREVIEW_ONLY", {k:v for k,v in result.items() if k not in {"entries", "retryAfterKey"}})

if __name__ == "__main__":
    main()
