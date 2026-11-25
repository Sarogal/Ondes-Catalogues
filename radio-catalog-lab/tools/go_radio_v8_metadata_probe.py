#!/usr/bin/env python3
"""Read-only first-pass ICY audit of all active signed v8 station variants.

No publication, no catalog changes, no credentials, no guesses about artists.
Positive stream evidence is NOT proof of display on the phone or Android Auto.
Run from the repository: python tools/go_radio_v8_metadata_probe.py --output metadata-v8.json
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
import socket
import subprocess
import threading
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from go_radio_v8_public_verifier import verify_remote, EXPECTED_V8
from probe_full_radio_streams_20261122 import IcyHTTPHandler

MAX_AUDIO_BYTES = 512 * 1024
MAX_INTERVAL = 128 * 1024
MAX_BLOCKS = 3
WALL_SECONDS = 18


def public_http_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Not a public HTTP(S) stream URL")
    # Reject private/reserved addresses, including on redirects. No proxy.
    for entry in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                    type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise ValueError("Non-public stream address")


class PublicRedirect(HTTPRedirectHandler):
    max_redirections = 4

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_exact(response, size: int) -> bytes:
    data = response.read(size)
    if len(data) != size:
        raise EOFError("Stream ended before expected ICY block")
    return data


def stream_title(block: bytes) -> dict | None:
    raw = block.rstrip(b"\x00")
    try:
        decoded = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        decoded = raw.decode("cp1252", errors="replace")
        encoding = "cp1252-fallback"
    # Delimiter is the field terminator, not an apostrophe inside a song name.
    match = re.search(r"(?:^|;)\s*StreamTitle\s*=\s*(['\"])(.*?)\1\s*(?:;|$)",
                      decoded, re.I | re.S)
    if not match:
        return None
    return {"raw": match.group(2).strip(), "encoding": encoding}


def read_icy(response, interval: int) -> dict:
    if interval <= 0 or interval > MAX_INTERVAL:
        return {"observation": "icy_interval_out_of_budget", "icy_metaint": interval}
    titles, blocks, read_bytes = [], 0, 0
    error = None
    for _ in range(MAX_BLOCKS):
        if read_bytes + interval + 1 + 4080 > MAX_AUDIO_BYTES:
            break
        try:
            read_exact(response, interval)
            size = read_exact(response, 1)[0] * 16
            block = read_exact(response, size)
        except (OSError, EOFError) as exc:
            error = type(exc).__name__
            break
        read_bytes += interval + 1 + size
        blocks += 1
        title = stream_title(block)
        if title and title["raw"]:
            titles.append(title)
            break
    observation = ("icy_title_observed" if titles else
                   "icy_no_title_in_sample" if blocks else "icy_sample_incomplete")
    return {"observation": observation, "icy_metaint": interval,
            "blocks": blocks, "bytes_read": read_bytes, "titles": titles,
            "read_error": error}


def probe(url: str) -> dict:
    public_http_url(url)
    opener = build_opener(ProxyHandler({}), IcyHTTPHandler(), PublicRedirect())
    request = Request(url, headers={"User-Agent": "GrossesOndes-MetadataAudit/1.0",
                                    "Icy-MetaData": "1", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=7) as response:
        headers = response.headers
        mime = headers.get("Content-Type", "")
        result = {"http_status": response.status, "content_type": mime,
                  "final_url": response.url, "icy_name": headers.get("icy-name"),
                  "icy_br": headers.get("icy-br")}
        interval = headers.get("icy-metaint")
        if interval is not None:
            try:
                result.update(read_icy(response, int(interval)))
            except ValueError:
                result["observation"] = "invalid_icy_interval"
        elif "mpegurl" in mime.lower() or urlsplit(response.url).path.lower().endswith(".m3u8"):
            result["observation"] = "hls_requires_id3_probe"
        else:
            result["observation"] = "no_icy_interval_observed"
        return result


def worker(url: str) -> dict:
    # Hard wall-clock limit includes DNS, redirects and trickle responses.
    try:
        done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--single"],
                              input=url, text=True, encoding="utf-8",
                              capture_output=True, timeout=WALL_SECONDS, check=False)
        if done.returncode:
            return {"observation": "probe_process_failed"}
        return json.loads(done.stdout)
    except subprocess.TimeoutExpired:
        return {"observation": "wall_timeout"}
    except (ValueError, OSError):
        return {"observation": "probe_process_failed"}


def audit(output: Path, workers: int) -> None:
    _, catalog = verify_remote()
    active = [s for s in catalog["stations"] if s["status"]["state"] == "active"]
    if len(active) != 285:
        raise ValueError("Unexpected signed v8 active count")
    variants = [(s, stream) for s in active for stream in s["streams"]]
    rows = {s["go_station_id"]: {"go_station_id": s["go_station_id"],
            "name": s["display_name"], "homepage": s.get("homepage"),
            "classification": "E", "classification_reason": "app_display_not_tested",
            "streams": []} for s in active}
    limiters = {urlsplit(v[1]['url']).hostname: threading.BoundedSemaphore(2) for v in variants}

    def guarded(item):
        url = item[1]['url']
        with limiters[urlsplit(url).hostname]:
            result = worker(url)
            result['observed_at'] = datetime.now(timezone.utc).isoformat()
            return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (station, stream), evidence in zip(variants, pool.map(guarded, variants)):
            rows[station["go_station_id"]]["streams"].append({
                "stream_id": stream["stream_id"], "url": stream["url"],
                "declared_codec": stream.get("codec"), "declared_protocol": stream.get("protocol"),
                "declared_state": stream.get("state"), "observed_at": datetime.now(timezone.utc).isoformat(),
                **evidence})
    results = list(rows.values())
    for row in results:
        row["icy_title_observed"] = any(v["observation"] == "icy_title_observed" for v in row["streams"])
        row["classification_reason"] = ("stream_title_present_app_display_unverified" if row["icy_title_observed"]
                                        else "insufficient_evidence_no_absence_claim")
    from collections import Counter
    report = {"signed_sequence": 8, "catalog_sha256": EXPECTED_V8,
              "scope": "first-pass HTTP/ICY only; HLS/ID3, official APIs and app display pending",
              "station_count": len(results), "stream_count": len(variants),
              "stations_with_observed_icy_title": sum(s["icy_title_observed"] for s in results),
              "station_classification_counts": dict(Counter(s["classification"] for s in results)),
              "stream_observation_counts": dict(Counter(v["observation"] for s in results for v in s["streams"])),
              "stations": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "stations"}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=6, choices=range(1, 9))
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single:
        try:
            result = probe(sys.stdin.read().strip())
        except Exception as exc:
            result = {"observation": "network_or_protocol_error", "error_type": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=True))
    elif args.output:
        audit(args.output, args.workers)
    else:
        parser.error("--output required")


if __name__ == "__main__":
    main()
