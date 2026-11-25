#!/usr/bin/env python3
"""Read-only discovery of public Icecast and AzuraCast metadata APIs.

One bounded probe per origin/protocol, exact mount match, no station whitelist.
Evidence only: matching fields do not prove synchronization with audible audio.
"""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
from urllib.request import ProxyHandler, Request, build_opener

from go_radio_v8_public_verifier import EXPECTED_V8, verify_remote
from go_radio_v8_metadata_probe import PublicRedirect, public_http_url
from go_radio_v8_metadata_second_pass import format_kind

MAX_JSON = 512 * 1024
PATHS = {"icecast": "/status-json.xsl", "azuracast": "/api/nowplaying"}


def origin(url):
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Invalid HTTP origin")
    return urlunsplit((u.scheme, u.netloc.lower(), "", "", ""))


def same_mount(a, b):
    try:
        return origin(a) == origin(b) and urlsplit(a).path == urlsplit(b).path
    except (ValueError, TypeError):
        return False


def clean(value):
    return " ".join(value.split())[:500] if isinstance(value, str) else ""


def icecast_records(data):
    sources = data.get("icestats", {}).get("source", [])
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        return []
    return [{"mount": s.get("listenurl"), "artist": clean(s.get("artist")),
             "title": clean(s.get("title")), "display_title": clean(s.get("display-title"))}
            for s in sources if isinstance(s, dict) and isinstance(s.get("listenurl"), str)]


def azuracast_records(data):
    if not isinstance(data, list):
        return []
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        station, now = row.get("station"), row.get("now_playing")
        if not isinstance(station, dict) or not isinstance(now, dict):
            continue
        song = now.get("song")
        if not isinstance(song, dict) or row.get("is_online") is not True:
            continue
        mounts = [station.get("listen_url")]
        for mount in station.get("mounts") or []:
            if isinstance(mount, dict):
                mounts.append(mount.get("url"))
        for mount in mounts:
            if isinstance(mount, str):
                result.append({"mount": mount, "artist": clean(song.get("artist")),
                               "title": clean(song.get("title")),
                               "display_title": clean(song.get("text")),
                               "played_at": now.get("played_at"), "duration": now.get("duration")})
    return result


def match(records, url, name):
    matches = [r for r in records if same_mount(r["mount"], url)]
    distinct = {json.dumps(r, sort_keys=True) for r in matches}
    if len(distinct) != 1:
        return None
    r = matches[0]
    artist, title = r["artist"], r["title"]
    if artist and title and title.casefold() != name.casefold() and artist.casefold() != name.casefold():
        return {**r, "kind": "explicit_artist_title"}
    raw = r["display_title"] or title
    if raw and format_kind(raw, name) == "current_parser_pair":
        return {**r, "kind": "combined_title_candidate"}
    return None


def fetch(endpoint, protocol):
    public_http_url(endpoint)
    opener = build_opener(ProxyHandler({}), PublicRedirect())
    with opener.open(Request(endpoint, headers={"User-Agent": "GrossesOndes-MetadataAudit/1.0",
                                                "Accept": "application/json",
                                                "Accept-Encoding": "identity"}), timeout=7) as response:
        if origin(response.url) != origin(endpoint):
            return {"status": "cross_origin_redirect", "records": []}
        body = response.read(MAX_JSON + 1)
    if len(body) > MAX_JSON:
        return {"status": "response_too_large", "records": []}
    data = json.loads(body)
    if protocol == "icecast" and isinstance(data, dict):
        records = icecast_records(data)
    elif protocol == "azuracast":
        records = azuracast_records(data)
    else:
        records = []
    return {"status": "json_records" if records else "no_recognized_records", "records": records}


def worker(job):
    endpoint, protocol = job
    try:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--single", protocol],
                           input=endpoint, text=True, capture_output=True, timeout=12)
        return json.loads(r.stdout) if r.returncode == 0 else {"status": "probe_failed", "records": []}
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return {"status": "probe_failed_or_timeout", "records": []}


def run(second, output):
    _, catalog = verify_remote()
    data = json.loads(second.read_text(encoding="utf-8"))
    if data["signed_sequence"] != 8 or data["catalog_sha256"] != EXPECTED_V8:
        raise ValueError("Wrong snapshot")
    signed = {s["go_station_id"]: s for s in catalog["stations"] if s["status"]["state"] == "active"}
    if {s["go_station_id"] for s in data["stations"]} != set(signed):
        raise ValueError("Incomplete evidence")
    targets, jobs = [], set()
    for row in data["stations"]:
        if row["format_evidence"] == "current_parser_pair_candidate":
            continue
        station = signed[row["go_station_id"]]
        streams = {s["stream_id"]: s for s in station["streams"]}
        for r in row["streams"]:
            stream = streams[r["stream_id"]]
            if r["url"] != stream["url"]:
                raise ValueError("URL does not match signed catalog")
            urls = {stream["url"]}
            # Redirect targets were observed by the trusted first/second public audit.
            # They are discovery candidates only; exact mount match is still required.
            for sample in (r["first"], r.get("repeat", {})):
                if isinstance(sample.get("final_url"), str):
                    urls.add(sample["final_url"])
            for url in sorted(urls):
                try:
                    base = origin(url)
                except ValueError:
                    continue
                targets.append((row["go_station_id"], station["display_name"], stream["stream_id"], url))
                jobs.update((base + path, protocol) for protocol, path in PATHS.items())
    jobs = sorted(jobs)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(zip(jobs, pool.map(worker, jobs)))
    candidates = []
    for gid, name, sid, url in targets:
        for protocol, path in PATHS.items():
            endpoint = origin(url) + path
            found = match(results[(endpoint, protocol)]["records"], url, name)
            if found:
                candidates.append({"go_station_id": gid, "name": name, "stream_id": sid,
                                   "observed_stream_url": url, "protocol": protocol,
                                   "endpoint": endpoint, "evidence": found})
    summary = {"target_stations": len({r[0] for r in targets}),
               "endpoint_probes": len(jobs),
               "endpoint_status_counts": dict(Counter(r["status"] for r in results.values())),
               "candidate_station_count": len({r["go_station_id"] for r in candidates}),
               "candidates": [{"id": r["go_station_id"], "name": r["name"], "protocol": r["protocol"],
                               "kind": r["evidence"]["kind"]} for r in candidates],
               "classification_note": "No production activation; verify freshness, timing, rights and app display."}
    output.write_text(json.dumps({"catalog_sha256": EXPECTED_V8, "summary": summary,
                                  "candidates": candidates,
                                  "endpoint_results": [{"endpoint": e, "protocol": p, "status": v["status"]}
                                                       for (e, p), v in results.items()]},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", choices=PATHS)
    parser.add_argument("--second", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.single:
        try:
            print(json.dumps(fetch(sys.stdin.read().strip(), args.single)))
        except Exception as exc:
            print(json.dumps({"status": type(exc).__name__, "records": []}))
    elif args.second and args.output:
        run(args.second, args.output)
    else:
        parser.error("--second and --output required")
