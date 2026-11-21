#!/usr/bin/env python3
"""Read-only live transport preflight for OPEN-ended radio candidates.

This script is NOT a signing, discovery whitelist or publication gate.
It never upgrades a candidate to 'verified'. An HTTP audio prefix only
proves transport at this moment; sustained playback and editorial source
verification remain independent mandatory gates. No credentials required.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)
import ssl

MAX_STREAM_BYTES = 16 * 1024
MAX_REPORT_BYTES = 200 * 1024
MAX_CANDIDATES = 250
MAX_STREAMS_PER_CANDIDATE = 12
_ALLOWED_CODECS = {"MP3", "AAC", "OGG"}
_GO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{3,127}$")


class CandidateError(ValueError):
    pass


def public_https(url: str) -> bool:
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username is not None
                or u.password is not None or u.fragment or u.port not in (None, 443)):
            return False
        host = u.hostname.lower().rstrip(".")
        if (host in {"localhost", "localhost.localdomain"} or
                host.endswith((".local", ".internal", ".localhost")) or
                "." not in host):
            return False
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return True  # Public-looking DNS hostname. The CI has no secrets.
        return ip.is_global
    except (ValueError, TypeError):
        return False


def validate_input(document: dict) -> list[dict]:
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise CandidateError("Unsupported candidate manifest")
    if document.get("publication_allowed") is not False:
        raise CandidateError("Candidate manifest cannot enable publication")
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise CandidateError("Unexpected candidate count")
    ids: set[str] = set()
    all_legacy_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict) or item.get("status") != "candidate":
            raise CandidateError("Only review candidates permitted")
        name = item.get("name")
        cid = item.get("candidate_id")
        if (not isinstance(name, str) or not name.strip() or
                not isinstance(cid, str) or not _GO_ID_RE.fullmatch(cid) or
                cid in ids):
            raise CandidateError("Invalid or duplicate candidate identity")
        ids.add(cid)
        for url_key in ("official_station_page", "official_stream_evidence"):
            if not public_https(item.get(url_key)):
                raise CandidateError("Official source must be public HTTPS")
        genres = item.get("genres")
        if (not isinstance(genres, list) or not genres or
                any(not isinstance(g, str) or not g.strip() for g in genres)):
            raise CandidateError("Missing genre evidence")
        aliases = item.get("known_legacy_ids", [])
        if not isinstance(aliases, list):
            raise CandidateError("Malformed legacy aliases")
        for alias in aliases:
            if (not isinstance(alias, str) or not alias.strip() or
                    alias in all_legacy_ids):
                raise CandidateError("Duplicate legacy identity")
            all_legacy_ids.add(alias)
        streams = item.get("streams")
        if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_STREAMS_PER_CANDIDATE:
            raise CandidateError("Unexpected stream count")
        urls = set()
        for stream in streams:
            if not isinstance(stream, dict) or not public_https(stream.get("url")):
                raise CandidateError("Invalid candidate stream")
            if stream.get("codec") not in _ALLOWED_CODECS:
                raise CandidateError("Unknown candidate codec")
            bitrate = stream.get("bitrate_kbps")
            if type(bitrate) is not int or not 0 <= bitrate <= 1024:
                raise CandidateError("Invalid claimed bitrate")
            if stream["url"] in urls:
                raise CandidateError("Duplicate candidate stream")
            urls.add(stream["url"])
        logos = item.get("logo_candidates", [])
        if (not isinstance(logos, list) or any(
                not isinstance(l, dict) or not public_https(l.get("url")) or
                l.get("state") != "unreviewed" for l in logos)):
            raise CandidateError("Logos must remain unreviewed pending byte audit")
    return candidates


class HttpsOnlyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl):
            raise CandidateError("Insecure or private redirect denied")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def audio_magic(payload: bytes, expected_codec: str) -> bool:
    if len(payload) < 128:
        return False
    if expected_codec == "OGG":
        return payload.startswith(b"OggS")
    if expected_codec == "MP3" and payload.startswith(b"ID3"):
        return True
    # Some servers prepend short ICY metadata; MP3/AAC sync frames are
    # detectable without decoding or redistributing copyrighted audio.
    limit = min(len(payload) - 1, 1024)
    for i in range(limit):
        a, b = payload[i], payload[i+1]
        if a != 0xff:
            continue
        if expected_codec == "AAC" and (b & 0xf6) == 0xf0:
            return True
        if expected_codec == "MP3" and (b & 0xe0) == 0xe0 and (b & 0x18) != 0x08:
            return True
    return False


def probe_stream(url: str, codec: str, timeout_s: int = 12) -> dict:
    result = {
        "url": url,
        "codec": codec,
        "transport_audio_prefix": False,
        "publication_allowed": False,
    }
    if not public_https(url):
        result["reason"] = "rejected_url"
        return result
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        HttpsOnlyRedirects(),
    )
    req = Request(url, headers={
        "User-Agent": "GrossesOndes/central-test-evidence-20261121",
        "Icy-MetaData": "0",
        "Accept": "audio/mpeg, audio/aac, audio/aacp, audio/ogg, */*",
    })
    start = time.monotonic()
    try:
        with opener.open(req, timeout=timeout_s) as res:
            final = res.geturl()
            if not public_https(final):
                raise CandidateError("Unsafe final stream URL")
            status = res.status
            content_type = res.headers.get("Content-Type", "").split(";")[0].strip().lower()
            payload = res.read(MAX_STREAM_BYTES)
            result.update({
                "http_status": status,
                "content_type": content_type,
                "final_url_host": urlsplit(final).hostname,
                "received_bytes": len(payload),
                "prefix_sha256": hashlib.sha256(payload).hexdigest(),
                "duration_ms": round((time.monotonic() - start) * 1000),
            })
            looks_audio = audio_magic(payload, codec)
            mime_audio = content_type.startswith(("audio/", "application/ogg")) or (
                content_type == "application/octet-stream" and looks_audio
            )
            result["transport_audio_prefix"] = (
                status in (200, 206) and looks_audio and mime_audio
            )
            result["reason"] = (
                "audio_prefix_only_not_continuous_playback"
                if result["transport_audio_prefix"]
                else "invalid_audio_payload_or_mime"
            )
    except (HTTPError, URLError, OSError, TimeoutError, CandidateError,
            socket.timeout) as error:
        # No secret-bearing arbitrary exception strings in logs.
        result["reason"] = type(error).__name__
        result["duration_ms"] = round((time.monotonic() - start) * 1000)
    return result


def evaluate(document: dict, *, allow_network: bool) -> dict:
    candidates = validate_input(document)
    report = {
        "schema_version": 1,
        "evidence_kind": "transport_preflight_not_editorial_approval",
        "publication_allowed": False,
        "signed_release_generated": False,
        "candidate_count": len(candidates),
        "checked_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "candidates": [],
    }
    for item in candidates:
        stream_reports = [
            probe_stream(s["url"], s["codec"]) if allow_network else {
                "url": s["url"], "codec": s["codec"],
                "transport_audio_prefix": False, "reason": "offline_preflight_only",
                "publication_allowed": False,
            }
            for s in item["streams"]
        ]
        report["candidates"].append({
            "candidate_id": item["candidate_id"],
            "name": item["name"],
            "genres": item["genres"],
            "official_station_page": item["official_station_page"],
            "official_stream_evidence": item["official_stream_evidence"],
            "known_legacy_ids": item.get("known_legacy_ids", []),
            "transport": stream_reports,
            "logo_candidates": item.get("logo_candidates", []),
            "requires_audio_continuity_review": True,
            "requires_logo_byte_sha_review": True,
            "editorial_state": "candidate",
        })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-probe", action="store_true",
                        help="Opt-in to bounded, read-only HTTPS stream evidence")
    args = parser.parse_args()
    if args.manifest.stat().st_size > MAX_REPORT_BYTES:
        raise CandidateError("Input too large")
    doc = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = evaluate(doc, allow_network=args.live_probe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    total = sum(len(item["transport"]) for item in report["candidates"])
    passing = sum(int(stream["transport_audio_prefix"])
                  for item in report["candidates"] for stream in item["transport"])
    print(json.dumps({
        "status": "GO_RADIO_CANDIDATE_EVIDENCE_ONLY",
        "candidates": len(report["candidates"]),
        "audio_prefix_probes": f"{passing}/{total}",
        "publication_allowed": False,
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
