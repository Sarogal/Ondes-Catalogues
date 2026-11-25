#!/usr/bin/env python3
"""Bounded HLS/ID3 evidence on signed variants identified by first-pass ICY.

No playlist execution or ffmpeg networking. HTTP(S) targets are checked before
opening and on redirects; segments are sampled, not played. No absence claim.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from go_radio_v8_public_verifier import EXPECTED_V8, verify_remote
from go_radio_v8_metadata_probe import PublicRedirect, public_http_url
from probe_full_radio_streams_20261122 import IcyHTTPHandler

MAX_PLAYLIST = 64 * 1024
MAX_SEGMENT = 256 * 1024
WALL_SECONDS = 25


def fetch(url, limit):
    public_http_url(url)
    opener = build_opener(ProxyHandler({}), IcyHTTPHandler(), PublicRedirect())
    request = Request(url, headers={"User-Agent": "GrossesOndes-MetadataAudit/1.0",
                                    "Accept-Encoding": "identity"})
    with opener.open(request, timeout=7) as response:
        return response.read(limit), response.url


def playlist_target(payload, base):
    if len(payload) >= MAX_PLAYLIST:
        return None, "playlist_over_budget"
    text = payload.decode("utf-8-sig", errors="replace")
    if not text.startswith("#EXTM3U"):
        return None, "not_m3u8"
    if any(not re.search(r"METHOD=NONE(?:,|$)", line)
           for line in text.splitlines() if line.startswith("#EXT-X-KEY:")):
        return None, "encrypted_hls_not_probed"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Master: prefer an explicit audio rendition, else first variant.
    if any(line.startswith("#EXT-X-STREAM-INF:") for line in lines):
        for line in lines:
            if line.startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in line:
                match = re.search(r'\bURI="([^"]+)"', line)
                if match:
                    return urljoin(base, match.group(1)), "master_audio"
        for i, line in enumerate(lines[:-1]):
            if line.startswith("#EXT-X-STREAM-INF:") and not lines[i+1].startswith("#"):
                return urljoin(base, lines[i+1]), "master_variant"
    # Choose newest complete listed segment, never low-latency PART or preload.
    if any(line.startswith("#EXTINF:") for line in lines):
        targets = [line for line in lines if not line.startswith("#")]
        if targets:
            return urljoin(base, targets[-1]), "media_segment"
    return None, "playlist_no_supported_target"


def synchsafe(data):
    if len(data) != 4 or any(b & 0x80 for b in data):
        raise ValueError("invalid synchsafe size")
    value = 0
    for b in data:
        value = (value << 7) | b
    return value


def id3_evidence(payload):
    """Direct ID3v2.3/2.4 frames only; TS-split/encrypted tags remain unknown."""
    found, tags = [], 0
    offset = 0
    while tags < 8:
        start = payload.find(b"ID3", offset)
        if start < 0 or start + 10 > len(payload):
            break
        offset = start + 3
        version, flags = payload[start+3], payload[start+5]
        if version not in (3, 4) or flags:
            continue
        try:
            size = synchsafe(payload[start+6:start+10])
        except ValueError:
            continue
        end = start + 10 + size
        if size <= 0 or end > len(payload):
            continue
        tags += 1
        pos = start + 10
        fields = {}
        while pos + 10 <= end:
            name = payload[pos:pos+4]
            if not re.fullmatch(rb"[A-Z0-9]{4}", name):
                break
            try:
                length = (synchsafe(payload[pos+4:pos+8]) if version == 4
                          else int.from_bytes(payload[pos+4:pos+8], "big"))
            except ValueError:
                break
            frame = payload[pos+10:pos+10+length]
            if length <= 0 or pos+10+length > end:
                break
            if name in (b"TPE1", b"TIT2") and frame and payload[pos+8:pos+10] == b"\x00\x00":
                encoding = {0: "latin1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(frame[0])
                if encoding:
                    try:
                        value = frame[1:].decode(encoding).strip("\x00 \r\n")
                    except UnicodeError:
                        value = ""
                    if value:
                        fields[name.decode()] = value
            pos += 10 + length
        if fields:
            found.append(fields)
        offset = end
    return {"complete_id3_tags": tags, "text_frames": found,
            "artist_title_pair_observed": any(x.get("TPE1") and x.get("TIT2") for x in found)}


def probe(url):
    current = url
    for _ in range(3):
        payload, final = fetch(current, MAX_PLAYLIST)
        target, kind = playlist_target(payload, final)
        if not target:
            return {"observation": kind}
        if kind == "media_segment":
            data, _ = fetch(target, MAX_SEGMENT)
            evidence = id3_evidence(data)
            return {"observation": "hls_sample_observed", "sample_bytes": len(data), **evidence}
        current = target
    return {"observation": "playlist_depth_exceeded"}


def worker(url):
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--single"],
                                input=url, text=True, capture_output=True, timeout=WALL_SECONDS)
        return json.loads(result.stdout) if result.returncode == 0 else {"observation": "probe_failed"}
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return {"observation": "probe_failed_or_timeout"}


def run(first, output):
    _, catalog = verify_remote()
    data = json.loads(first.read_text(encoding="utf-8"))
    if data["signed_sequence"] != 8 or data["catalog_sha256"] != EXPECTED_V8:
        raise ValueError("Wrong source snapshot")
    signed = {(s["go_station_id"], v["stream_id"]): (s["display_name"], v["url"])
              for s in catalog["stations"] if s["status"]["state"] == "active"
              for v in s["streams"]}
    targets = []
    for s in data["stations"]:
        for v in s["streams"]:
            if v["observation"] == "hls_requires_id3_probe":
                key = (s["go_station_id"], v["stream_id"])
                name, url = signed[key]
                if url != v["url"]:
                    raise ValueError("Unsigned URL")
                targets.append((key, name, url))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [{"go_station_id": k[0], "stream_id": k[1], "name": n, **e}
                   for (k, n, _), e in zip(targets, pool.map(worker, (u for _, _, u in targets)))]
    summary = {"probed_hls_variants": len(results),
               "direct_id3_artist_title_pairs": sum(bool(r.get("artist_title_pair_observed")) for r in results),
               "observations": [{k: r[k] for k in ("go_station_id", "name", "observation")} for r in results],
               "limitations": "Direct contiguous ID3 text frames only; no absence claim, no app display proof."}
    output.write_text(json.dumps({"catalog_sha256": EXPECTED_V8, "summary": summary,
                                  "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", action="store_true")
    parser.add_argument("--first", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.single:
        try:
            print(json.dumps(probe(sys.stdin.read().strip())))
        except Exception as exc:
            print(json.dumps({"observation": "network_or_protocol_error", "error_type": type(exc).__name__}))
    elif args.first and args.output:
        run(args.first, args.output)
    else:
        parser.error("--first and --output required")
