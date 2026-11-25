#!/usr/bin/env python3
"""Bounded multi-window audio observation, not playback certification.

Three spaced samples on one connection. Never publish bytes, URLs or approval.
An open ICY connection with changing frames is stronger evidence, not proof
that a programme is live (an endless recording can emulate that behaviour).
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlunsplit

from radio_stream_technical_probe import (
    validate_endpoint, public_resolved_ips, IcyCompatibleHTTPResponse,
    frame_chain, REDIRECT_CODES, UnsafeEndpoint,
)
from radio_daily_qualification_dossiers import index, safe_digest
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_STATIONS = 6
WINDOW_BYTES = 4096
MAX_WINDOWS = 3
WINDOW_INTERVAL = 2.0
MAX_TOTAL_SECONDS = 20.0
MAX_INPUT = 12 * 1024 * 1024


def assess(windows, *, finite, icy, elapsed, ended):
    """Classify bounded observations; do not infer audio decoding or ownership."""
    chains = [frame_chain(x) for x in windows]
    digests = [hashlib.sha256(x).hexdigest() for x in windows]
    distinct = len(set(digests))
    consistent = len(chains) == MAX_WINDOWS and bool(chains[0]) and len(set(chains)) == 1
    if finite:
        verdict = "finite_response_review"
    elif ended:
        verdict = "early_end_review"
    elif consistent and distinct == MAX_WINDOWS and elapsed >= 2 * WINDOW_INTERVAL:
        verdict = "continuous_icy_frame_indication" if icy else "continuous_frames_unbound"
    else:
        verdict = "insufficient_continuity_evidence"
    return {"verdict": verdict, "windowCount": len(windows),
            "sampleBytes": sum(map(len, windows)), "elapsedMs": round(elapsed * 1000),
            "coherentWindowCount": sum(bool(x) for x in chains),
            "distinctWindowCount": distinct, "frameCodec": chains[0] if consistent else None,
            "finiteResponse": finite, "icyHeaderPresent": icy, "earlyEnd": ended}


MAX_METADATA_INTERVAL = 131072
MAX_METADATA_BLOCKS = 3


def read_icy_titles(response, interval, deadline, clock):
    """Read framed ICY blocks; never interpret the intervening audio as text."""
    if not isinstance(interval, str) or not interval.isascii() or not interval.isdigit() or len(interval) > 6:
        return {"verdict": "metadata_not_advertised", "titleHints": []}
    n = int(interval)
    if not 1 <= n <= MAX_METADATA_INTERVAL:
        return {"verdict": "metadata_interval_out_of_budget", "titleHints": []}
    def exact(count):
        data = bytearray()
        while len(data) < count:
            if clock() >= deadline:
                raise TimeoutError("metadata deadline")
            part = response.read1(min(8192, count-len(data)))
            if not part:
                raise EOFError("metadata response ended")
            data.extend(part)
        return bytes(data)
    hints = []
    try:
        for _ in range(MAX_METADATA_BLOCKS):
            exact(n)
            size = exact(1)[0] * 16
            if not size:
                continue
            raw = exact(size).rstrip(b"\0")
            # The server may use UTF-8 or legacy Latin-1.
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            m = re.search(r"(?:^|;)\s*StreamTitle='(.*?)';", text, re.S|re.I)
            if not m:
                continue
            value = m.group(1).strip()
            # Artist/title syntax is a hint, not a verified artist identity.
            if not 0 < len(value) <= 240 or any(ord(c)<32 for c in value):
                continue
            if re.search(r"https?://|www\.|@|[?=]", value, re.I):
                continue
            if value.count(" - ") != 1:
                continue
            artist, title = (x.strip() for x in value.split(" - ", 1))
            if not (2 <= len(artist) <= 100 and 1 <= len(title) <= 140 and any(c.isalpha() for c in artist)):
                continue
            item = {"artistHint": artist, "titleSha256": safe_digest(title)}
            if item not in hints:
                hints.append(item)
    except (EOFError, TimeoutError, OSError, http.client.HTTPException):
        pass
    return {"verdict": "icy_artist_title_hint" if hints else "metadata_no_parseable_title",
            "titleHints": hints}


def observe_url(raw_url, *, clock=time.monotonic, sleep=time.sleep, metadata=False):
    deadline = clock() + MAX_TOTAL_SECONDS
    current = raw_url
    visited = set()
    for _ in range(4):
        p = validate_endpoint(current)
        if current in visited:
            raise ValueError("redirect cycle")
        visited.add(current)
        host = p.hostname
        port = p.port or (443 if p.scheme == "https" else 80)
        ip = public_resolved_ips(host, port)[0]
        if clock() >= deadline:
            raise TimeoutError("probe deadline")
        kwargs = {"timeout": min(4, deadline-clock())}
        if p.scheme == "https":
            connection = http.client.HTTPSConnection(host, port, context=ssl.create_default_context(), **kwargs)
        else:
            connection = http.client.HTTPConnection(host, port, **kwargs)
        connection.response_class = IcyCompatibleHTTPResponse
        def pinned(address, timeout=None, source_address=None):
            if address != (host, port):
                raise UnsafeEndpoint("unexpected_connection_target")
            return socket.create_connection((ip, port), timeout=min(4, max(.1, deadline-clock())))
        connection._create_connection = pinned
        try:
            connection.request("GET", urlunsplit(("", "", p.path or "/", p.query, "")),
                               headers={"Accept": "audio/*,application/octet-stream,*/*;q=0.2",
                                        "Icy-MetaData": "1" if metadata else "0", "Accept-Encoding": "identity",
                                        "User-Agent": "GrossesOndesContinuityPreview/1.0",
                                        "Connection": "close"})
            response = connection.getresponse()
            if response.status in REDIRECT_CODES:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("missing redirect")
                target = urljoin(current, location)
                dest = validate_endpoint(target)
                if p.scheme == "https" and dest.scheme != "https":
                    raise UnsafeEndpoint("tls_downgrade")
                current = target
                continue
            if response.status not in (200, 206):
                raise ValueError("unsuccessful response")
            if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
                raise ValueError("encoded response")
            finite = (response.status == 206 or response.getheader("Content-Length") is not None
                      or response.getheader("Content-Range") is not None)
            icy = any(response.getheader(k) for k in ("icy-name", "icy-br", "icy-metaint"))
            mime = (response.getheader("Content-Type") or "").split(";")[0].lower()
            if "mpegurl" in mime or "scpls" in mime or "playlist" in mime:
                return {"verdict": "playlist_requires_separate_validation", "windowCount": 0}
            if metadata:
                if finite or not (mime.startswith("audio/") or mime == "application/octet-stream"):
                    return {"verdict": "metadata_non_live_response", "titleHints": []}
                return read_icy_titles(response, response.getheader("icy-metaint"), deadline, clock)
            if finite:
                return assess([], finite=True, icy=icy, elapsed=0, ended=False)
            windows = []
            start = clock()
            ended = False
            for i in range(MAX_WINDOWS):
                if i:
                    if clock() + WINDOW_INTERVAL >= deadline:
                        raise TimeoutError("probe deadline")
                    sleep(WINDOW_INTERVAL)
                chunk = bytearray()
                while len(chunk) < WINDOW_BYTES:
                    if clock() >= deadline:
                        raise TimeoutError("probe deadline")
                    data = response.read1(WINDOW_BYTES-len(chunk))
                    if not data:
                        ended = True
                        break
                    chunk.extend(data)
                if chunk:
                    windows.append(bytes(chunk))
                if ended:
                    break
            return assess(windows, finite=False, icy=icy, elapsed=clock()-start, ended=ended)
        finally:
            connection.close()
    raise ValueError("redirect budget")


def positive_dates(prior, day, digest, verdict, positive_verdict):
    """Retain positive dates only for the exact fingerprint, capped at 30."""
    days = []
    if prior and prior.get("streamSha256") == digest:
        days = prior.get("positiveObservationDates", [])
        if not isinstance(days, list) or len(days)>30:
            raise ValueError("invalid positive history")
        days = [parse_day(x) for x in days]
        if days != sorted(set(days)) or any(x>day for x in days):
            raise ValueError("invalid positive dates")
        if prior.get("verdict") == positive_verdict:
            days = sorted(set(days + [parse_day(prior["observedDate"])]))
    if verdict == positive_verdict:
        days = sorted(set(days + [day]))
    return days[-30:]


def collect(discovery, reconciliation, audio, editorial, *, previous=None, limit=0, observe=observe_url):
    day = parse_day(discovery.get("scanDate"))
    if not 0 <= limit <= MAX_STATIONS:
        raise ValueError("station budget")
    for report, key, count in ((discovery, "scanDate", None),
                               (audio, "observationDate", "technicallyQualifiedCount"),
                               (editorial, "scanDate", "editoriallyApprovedCount")):
        if (report.get("schemaVersion") != 1 or report.get("publicationAllowed") is not False
                or report.get(key) != day or (count and report.get(count) != 0)):
            raise ValueError("invalid evidence input")
    if (reconciliation.get("schemaVersion") != 1 or reconciliation.get("scanDate") != day
            or reconciliation.get("automaticAdmissionAllowed") is not False
            or reconciliation.get("catalogChanged") is not False):
        raise ValueError("invalid reconciliation")
    candidates, rec = index(discovery, "candidates"), index(reconciliation, "candidates")
    a, e = index(audio, "records"), index(editorial, "records")
    if set(candidates) != set(rec):
        raise ValueError("UUID mismatch")
    old = {}
    if previous is not None:
        if (previous.get("schemaVersion") != 1 or previous.get("publicationAllowed") is not False
                or previous.get("technicallyQualifiedCount") != 0
                or parse_day(previous["scanDate"]) > day):
            raise ValueError("invalid prior continuity report")
        old = index(previous, "records")
        for row in old.values():
            if (row.get("publicationAllowed") is not False or row.get("technicalQualified") is not False
                    or parse_day(row["observedDate"]) > day
                    or not SHA256_RE.fullmatch(row.get("streamSha256") or "")):
                raise ValueError("invalid prior continuity row")
    retained = {uid: dict(row, observedInScan=False) for uid,row in old.items() if uid not in candidates}
    queue = []
    for uid, row in sorted(candidates.items()):
        url = row.get("streamUrl")
        digest = safe_digest(url)
        if rec[uid]["classification"] != "unmapped_candidate" or not digest:
            continue
        if row.get("editorialSignal") == "electronic_context_review":
            continue
        prior = old.get(uid)
        if prior and prior["streamSha256"] == digest:
            retained[uid] = dict(prior, observedInScan=True)
            if prior["observedDate"] == day:
                continue
        if (a.get(uid, {}).get("streamSha256") != digest
                or a[uid].get("lastVerdict") not in ("audio_sample_ok", "audio_mime_only")):
            continue
        if a[uid].get("technicalQualified") is not False or a[uid].get("publicationAllowed") is not False:
            raise ValueError("unexpected audio approval")
        try:
            validate_endpoint(url)
        except ValueError:
            continue
        rank = (bool(e.get(uid, {}).get("declaredStreamLinked")) and e[uid].get("streamSha256") == digest,
                bool(a[uid].get("liveFrameEvidenceDates")))
        queue.append((uid in retained, not rank[0], not rank[1], uid, url, digest))
    selected = sorted(queue)[:limit]
    def check(entry):
        _, _, _, uid, url, digest = entry
        try:
            evidence = observe(url)
        except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
            evidence = {"verdict": "connection_or_protocol_review", "windowCount": 0}
        dates = positive_dates(old.get(uid), day, digest, evidence.get("verdict"), "continuous_icy_frame_indication")
        return uid, {"stationuuid": uid, "streamSha256": digest, "observedDate": day,
                     "positiveObservationDates": dates,
                     "observedInScan": True, "technicalQualified": False,
                     "publicationAllowed": False, **evidence}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for uid, result in pool.map(check, selected):
            retained[uid] = result
    records = [retained[k] for k in sorted(retained)]
    for row in records:
        row["positiveObservationDates"] = positive_dates(row, day, row["streamSha256"], None, "continuous_icy_frame_indication")
    return {"schemaVersion": 1, "scanDate": day, "publicationAllowed": False,
            "technicallyQualifiedCount": 0, "attemptedCount": len(selected),
            "continuousIcyCount": sum(x["verdict"] == "continuous_icy_frame_indication" for x in records),
            "finiteResponseCount": sum(x["verdict"] == "finite_response_review" for x in records),
            "records": records}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("discovery", "reconciliation", "audio", "editorial", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--previous", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--allow-network", action="store_true")
    args = p.parse_args()
    if args.limit and not args.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size > MAX_INPUT:
            raise ValueError("oversized input")
        return json.loads(path.read_text())
    report = collect(*(load(getattr(args,k)) for k in ("discovery","reconciliation","audio","editorial")),
                     previous=load(args.previous) if args.previous else None, limit=args.limit)
    payload = json.dumps(report, indent=2) + "\n"
    if len(payload.encode()) > MAX_INPUT:
        raise ValueError("oversized output")
    args.output.write_text(payload)
    print("RADIO_CONTINUITY_PREVIEW_ONLY", {k:v for k,v in report.items() if k!="records"})


if __name__ == "__main__":
    main()
