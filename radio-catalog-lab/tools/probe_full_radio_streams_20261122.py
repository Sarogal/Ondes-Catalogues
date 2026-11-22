#!/usr/bin/env python3
"""Bounded live playback probe for the staged Grosses Ondes catalog.

Read-only by default; records exact reasons rather than silently deleting
stations. --enriched-out writes a NEW file marking only decoded streams verified.
Never modifies the input or publishes a signed pointer.

Example:
 python tools/radio_catalog_stream_probe.py \
   staging/radio-catalog/v1/central-authoritative-full-candidate-20261122.json \
   --report /tmp/stream-probe-report.json --enriched-out /tmp/decoded-catalog.json
"""
from __future__ import annotations

import argparse
import copy
import http.client
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPRedirectHandler, Request, build_opener

from radio_catalog_guard import safe_url, validate_catalog

MAX_SAMPLE_BYTES = 131072
AUDIO_HEADER = re.compile(r"Stream #\d+:\d+.*Audio:", re.I)
FRAME_HEADER = re.compile(r"time=\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def check_public_host(url: str) -> None:
    """Refuse private/localhost literal IPs AND DNS records before connecting."""
    if not safe_url(url):
        raise ValueError("unsafe_url")
    host = urlsplit(url).hostname
    if host is None:
        raise ValueError("missing_host")
    try:
        records = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError("dns_failure") from exc
    if not records:
        raise ValueError("dns_empty")
    addresses = {entry[4][0] for entry in records}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("dns_non_public_address")



class IcyHTTPResponse(http.client.HTTPResponse):
    """Treat legacy Icecast ICY status as HTTP/1.0, never bypass URL checks."""

    def _read_status(self):
        raw = self.fp.readline(http.client._MAXLINE + 1)
        if len(raw) > http.client._MAXLINE:
            raise http.client.LineTooLong("status line")
        line = raw.decode("iso-8859-1")
        parts = line.split(None, 2)
        if len(parts) < 2:
            raise http.client.BadStatusLine(line)
        version = "HTTP/1.0" if parts[0] == "ICY" else parts[0]
        if not version.startswith("HTTP/"):
            raise http.client.BadStatusLine(line)
        try:
            status = int(parts[1])
        except ValueError as error:
            raise http.client.BadStatusLine(line) from error
        if not 100 <= status <= 999:
            raise http.client.BadStatusLine(line)
        reason = parts[2].strip() if len(parts) == 3 else ""
        return version, status, reason


class IcyHTTPConnection(http.client.HTTPConnection):
    response_class = IcyHTTPResponse


class IcyHTTPHandler(HTTPHandler):
    def http_open(self, req):
        return self.do_open(IcyHTTPConnection, req)


class CheckedRedirects(HTTPRedirectHandler):
    max_redirections = 4

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_thread_local = threading.local()


def opener():
    if not hasattr(_thread_local, "opener"):
        _thread_local.opener = build_opener(IcyHTTPHandler(), CheckedRedirects())
    return _thread_local.opener


def download_sample(url: str, *, timeout: int = 9) -> tuple[bytes, str, str]:
    check_public_host(url)
    request = Request(url, headers={
        "User-Agent": "GrossesOndesRadioProbe/1.0 (+offline-catalog-staging)",
        "Accept": "audio/*, application/ogg, application/octet-stream;q=0.8, */*;q=0.5",
        "Icy-MetaData": "0",
    })
    with opener().open(request, timeout=timeout) as resp:
        final = resp.geturl()
        check_public_host(final)
        mime = resp.headers.get_content_type().lower()
        sample = resp.read(MAX_SAMPLE_BYTES)
    return sample, mime, final


def decode_sample(payload: bytes, ffmpeg: str | None) -> tuple[bool, str]:
    if not ffmpeg:
        return False, "ffmpeg_missing"
    if not payload:
        return False, "empty_audio_body"
    try:
        result = subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info",
            "-i", "pipe:0", "-t", "2", "-vn", "-f", "null", "-"
        ], input=payload, capture_output=True, timeout=12, check=False)
    except subprocess.TimeoutExpired:
        return False, "decoder_timeout"
    except OSError:
        return False, "decoder_not_executable"
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0 or not AUDIO_HEADER.search(stderr):
        return False, "decoder_no_playable_audio"
    # A mere syntactically valid URL or MP3 header is NOT enough to verify.
    matches = FRAME_HEADER.findall(stderr)
    if not matches:
        return False, "decoder_no_output_frames"
    duration = max(int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in matches)
    if duration < 0.5:
        return False, "decoder_insufficient_audio"
    return True, "audio_decoded"


def inspect_stream(station: str, stream: dict, ffmpeg: str | None, checked: str):
    url = stream.get("url")
    record = {"go_station_id": station, "stream_id": stream.get("stream_id"),
              "url": url, "checked_at": checked, "verified": False,
              "result": "unprobed", "mime_type": None, "bytes_read": 0}
    try:
        data, mime, final_url = download_sample(url)
        record["mime_type"] = mime
        record["bytes_read"] = len(data)
        record["redirected"] = final_url != url
        if data[:16].lstrip().startswith((b"#EXTM3U", b"[playlist]")) or \
                mime in ("application/vnd.apple.mpegurl", "application/x-mpegurl"):
            record["result"] = "playlist_needs_bounded_segment_probe"
        elif data.lstrip().startswith(b"<html") or data.lstrip().startswith(b"<!DOCTYPE"):
            record["result"] = "html_not_audio"
        else:
            record["verified"], record["result"] = decode_sample(data, ffmpeg)
    except HTTPError as exc:
        record["result"] = f"http_{exc.code}"
    except http.client.HTTPException as exc:
        record["result"] = f"invalid_http_status_{type(exc).__name__}"
    except URLError as exc:
        record["result"] = f"url_error_{str(exc.reason)[:90]}"
    except ValueError as exc:
        record["result"] = str(exc)
    except (OSError, TimeoutError) as exc:
        record["result"] = f"io_error_{type(exc).__name__}"
    return record


def probe(catalog: dict, *, max_streams: int | None = None, offset: int = 0,
          workers: int = 12, ffmpeg: str | None = None):
    if max_streams is not None and max_streams <= 0:
        raise ValueError("max_streams must be positive")
    if offset < 0:
        raise ValueError("offset must be nonnegative")
    if not 1 <= workers <= 24:
        raise ValueError("workers must be between 1 and 24")
    errors = validate_catalog(catalog, mode="staging")
    if errors:
        raise ValueError("invalid input catalog: " + "; ".join(errors[:4]))
    checked = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    jobs = [(s["go_station_id"], stream) for s in catalog["stations"]
            for stream in s["streams"] if stream["state"] != "disabled"]
    selected = jobs[offset:offset + max_streams] if max_streams else jobs[offset:]
    # Do not hammer providers with many similar genre feeds on one host.
    limiters = {}
    for _, stream in selected:
        host = urlsplit(stream["url"]).hostname or ""
        limiters.setdefault(host, threading.BoundedSemaphore(2))

    def guarded(item):
        go_id, stream = item
        sem = limiters[urlsplit(stream["url"]).hostname or ""]
        with sem:
            return inspect_stream(go_id, stream, ffmpeg, checked)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(guarded, selected))
    updated = copy.deepcopy(catalog)
    checks = {(r["go_station_id"], r["stream_id"]): r for r in results}
    for st in updated["stations"]:
        for stream in st["streams"]:
            status = checks.get((st["go_station_id"], stream["stream_id"]))
            if status and status["verified"]:
                stream["state"] = "verified"
                stream["last_checked_at"] = checked
            # A single failed check does not delete/disable any known stream.
    counts = {}
    for row in results:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    report = {
        "source_release_sequence": catalog["release_sequence"],
        "checked_at": checked, "requested_streams": len(jobs),
        "first_stream_index": offset,
        "probed_streams": len(results), "verified_this_run":
            sum(row["verified"] for row in results),
        "reason_counts": dict(sorted(counts.items())), "rows": results,
        "publication_authorized": False,
        "note": "Network probe only. No stream removed; a single decoded sample is not a long-term availability guarantee."
    }
    return updated, report



def installed_ffmpeg() -> str | None:
    direct = shutil.which("ffmpeg")
    if direct:
        return direct
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--enriched-out", type=Path)
    parser.add_argument("--max-streams", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    for f in (args.report, args.enriched_out):
        if f and f.exists():
            parser.error("refusing to overwrite existing report or catalog")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    updated, result = probe(catalog, max_streams=args.max_streams, offset=args.offset,
                            workers=args.workers, ffmpeg=installed_ffmpeg())
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    if args.enriched_out:
        args.enriched_out.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("requested_streams", "probed_streams", "verified_this_run", "reason_counts")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
