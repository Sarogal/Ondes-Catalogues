#!/usr/bin/env python3
"""Bounded, SSRF-aware audio *technical evidence* probe for radio candidates.

No publisher, no catalogue writes, no logo fetch, no station-specific logic.
Network probing is explicitly opt-in and capped. Failure is NEVER a deletion.
The private/signed publisher must NOT treat this as editorial approval.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from radio_stream_playlist_preview import playlist_hint
from radio_stream_continuity_evidence import observe_continuity

MAX_BYTES = 512
MAX_REDIRECTS = 3
CONNECT_TIMEOUT = 7.0
MAX_CANDIDATES = 5
MAX_INPUT_SIZE = 10_000_000
USER_AGENT = "GrossesOndesStreamQualifier/0.1 (+https://grosses-ondes.fr/)"
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class ResponseSample:
    status: int
    content_type: str
    location: str
    body: bytes
    continuity: dict | None = None


@dataclass(frozen=True)
class ProbeResult:
    stationuuid: str
    verdict: str
    reason: str
    format_hint: str
    redirect_count: int
    sample_bytes: int
    stream_sha256: str

    def to_json(self) -> dict:
        return {
            "stationuuid": self.stationuuid,
            "verdict": self.verdict,
            "reason": self.reason,
            "formatHint": self.format_hint,
            "redirectCount": self.redirect_count,
            "sampleBytes": self.sample_bytes,
            "streamSha256": self.stream_sha256,
            "publicationAllowed": False,
        }


class UnsafeEndpoint(ValueError):
    pass


def validate_endpoint(raw_url: object) -> urllib.parse.SplitResult:
    """Reject local IPs, credentials and invalid URL syntax before DNS."""
    if not isinstance(raw_url, str) or not 1 <= len(raw_url) <= 2048:
        raise UnsafeEndpoint("bad_url")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw_url):
        raise UnsafeEndpoint("control_character")
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise UnsafeEndpoint("scheme_or_host")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeEndpoint("userinfo_forbidden")
        if parsed.fragment or parsed.hostname.endswith(".") or "%" in parsed.netloc:
            raise UnsafeEndpoint("fragment_or_encoded_host")
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise UnsafeEndpoint("invalid_port")
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise UnsafeEndpoint("local_hostname")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise UnsafeEndpoint("single_label_hostname")
            if len(host) > 253 or not re.fullmatch(r"[a-z0-9.-]+", host):
                raise UnsafeEndpoint("invalid_hostname")
            if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                   for label in host.split(".")):
                raise UnsafeEndpoint("invalid_hostname")
        else:
            if not ip.is_global:
                raise UnsafeEndpoint("private_ip")
        return parsed
    except (TypeError, ValueError) as error:
        if isinstance(error, UnsafeEndpoint):
            raise
        raise UnsafeEndpoint("bad_url") from error


def public_resolved_ips(host: str, port: int, resolver=socket.getaddrinfo) -> list[str]:
    """Reject mixed public/private DNS results; pin each connection to a safe IP."""
    try:
        records = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as error:
        raise UnsafeEndpoint("dns_failed") from error
    addresses: list[str] = []
    for record in records:
        if len(record) < 5 or not record[4]:
            raise UnsafeEndpoint("malformed_dns")
        try:
            ip = ipaddress.ip_address(record[4][0])
        except ValueError as error:
            raise UnsafeEndpoint("malformed_dns") from error
        if not ip.is_global:
            raise UnsafeEndpoint("private_dns_answer")
        if str(ip) not in addresses:
            addresses.append(str(ip))
    if not addresses:
        raise UnsafeEndpoint("dns_empty")
    return addresses


def classify_sample(body: bytes, content_type: str) -> tuple[str, str]:
    """Only positive byte signatures yield audio evidence.

    HLS, PLS, M3U and unrecognized formats require a separate verified
    playlist/format-specific implementation, never blind URL following.
    """
    mime = content_type.split(";", 1)[0].strip().lower()
    if body.startswith((b"#EXTM3U", b"[playlist]", b"[Playlist]")) or (
        "mpegurl" in mime or "scpls" in mime or "playlist" in mime or
        mime in ("audio/x-mpegurl", "application/vnd.apple.mpegurl")
    ):
        return ("playlist_pending", "playlist")
    if body.startswith(b"ID3"):
        return ("audio_sample_ok", "mp3_id3")
    if len(body) >= 4 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0:
        # Require plausible MPEG or AAC frame header fields, not only 11
        # synchronization bits which can appear in arbitrary binary.
        mpeg_version = (body[1] >> 3) & 3
        mpeg_layer = (body[1] >> 1) & 3
        bitrate_index = (body[2] >> 4) & 15
        sampling_index = (body[2] >> 2) & 3
        mpeg_ok = (mpeg_version != 1 and mpeg_layer != 0 and
                   bitrate_index not in (0, 15) and sampling_index != 3)
        aac_ok = (body[1] & 0xF6) == 0xF0 and sampling_index != 3
        if mpeg_ok or aac_ok:
            return ("audio_sample_ok", "mpeg_or_aac_frame")
    if body.startswith(b"OggS"):
        # Ogg can contain video; only well-known audio codec identifiers
        # count as audio evidence in this bounded sample.
        if any(marker in body[:MAX_BYTES] for marker in (
            b"OpusHead", b"\x01vorbis", b"Speex   ", b"fLaC"
        )):
            return ("audio_sample_ok", "ogg_audio_codec")
        return ("container_pending", "ogg_codec_unconfirmed")
    if body.startswith(b"fLaC"):
        return ("audio_sample_ok", "flac")
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WAVE":
        return ("audio_sample_ok", "wav")
    if body.startswith(b"\x1a\x45\xdf\xa3"):
        return ("container_pending", "webm_codec_unconfirmed")
    if len(body) >= 12 and body[4:8] == b"ftyp":
        return ("container_pending", "mp4_codec_unconfirmed")
    if mime.startswith(("audio/", "video/")):
        return ("audio_mime_only", "unrecognized_audio_payload")
    return ("not_confirmed_audio", "unknown")


class IcyCompatibleHTTPResponse(http.client.HTTPResponse):
    """Accept legacy Icecast 'ICY 200 OK' while keeping HTTP status checks."""

    def _read_status(self):
        line = str(self.fp.readline(http.client._MAXLINE + 1), "iso-8859-1")
        if len(line) > http.client._MAXLINE:
            raise http.client.LineTooLong("status line")
        if not line:
            raise http.client.RemoteDisconnected("Peer closed before status")
        parts = line.split(None, 2)
        if len(parts) < 2:
            self._close_conn()
            raise http.client.BadStatusLine(line)
        version, raw_status = parts[:2]
        reason = parts[2] if len(parts) > 2 else ""
        if version == "ICY":
            version = "HTTP/1.0"
        elif not version.startswith("HTTP/"):
            self._close_conn()
            raise http.client.BadStatusLine(line)
        try:
            status = int(raw_status)
            if not 100 <= status <= 999:
                raise ValueError("invalid_status")
        except ValueError as error:
            self._close_conn()
            raise http.client.BadStatusLine(line) from error
        return version, status, reason


class PinnedHttpTransport:
    """No proxy, no implicit redirects, DNS check before *each* pinned hop.

    HTTPS preserves the original host for SNI and certificate verification
    while socket.create_connection uses only the checked IP address.
    """
    def __init__(self, resolver=socket.getaddrinfo, timeout: float = CONNECT_TIMEOUT,
                 extended_continuity: bool = False):
        self.resolver = resolver
        self.timeout = timeout
        self.extended_continuity = extended_continuity

    def request(self, url: str) -> ResponseSample:
        parsed = validate_endpoint(url)
        host = parsed.hostname
        assert host is not None
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        ips = public_resolved_ips(host, port, self.resolver)
        ip = ips[0]
        if parsed.scheme == "https":
            connection = http.client.HTTPSConnection(
                host, port, timeout=self.timeout, context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(host, port, timeout=self.timeout)
        connection.response_class = IcyCompatibleHTTPResponse
        # http.client.HTTP(S)Connection.connect() calls this factory to open
        # the socket. Original host is retained in HTTP Host / HTTPS SNI.
        def connect_checked(address, timeout=None, source_address=None):
            if address != (host, port):
                raise UnsafeEndpoint("unexpected_connection_target")
            return socket.create_connection((ip, port), timeout=self.timeout)
        connection._create_connection = connect_checked
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "audio/*,application/octet-stream,*/*;q=0.2",
                "Icy-MetaData": "0",
                "Connection": "close",
            }
            if not self.extended_continuity:
                headers["Range"] = "bytes=0-511"
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            # First read is always bounded, including manifest and redirects.
            data = response.read1(MAX_BYTES) if response.status in (200, 206) else b""
            mime = response.getheader("Content-Type", "") or ""
            continuity = None
            if (self.extended_continuity and response.status == 200 and
                    classify_sample(data, mime)[0] == "audio_sample_ok"):
                continuity = observe_continuity(
                    response, data,
                    content_length=response.getheader("Content-Length"),
                ).as_dict()
            return ResponseSample(
                status=int(response.status),
                content_type=mime,
                location=response.getheader("Location", "") or "",
                body=data,
                continuity=continuity,
            )
        finally:
            connection.close()


def probe_url(raw_url: str, request: Callable[[str], ResponseSample]) -> dict:
    """No stream bytes or raw URL written into the result."""
    fingerprint = hashlib.sha256(raw_url.encode("utf-8")).hexdigest() if (
        isinstance(raw_url, str)) else ""
    redirects = 0
    playlist_follows = 0
    visited: set[str] = set()
    current = raw_url
    try:
        while True:
            original = validate_endpoint(current)
            if current in visited:
                return {"verdict": "needs_review", "reason": "redirect_cycle",
                        "formatHint": "", "redirectCount": redirects, "sampleBytes": 0,
                        "streamSha256": fingerprint}
            visited.add(current)
            sample = request(current)
            if sample.status in REDIRECT_CODES:
                if redirects >= MAX_REDIRECTS or not sample.location:
                    verdict, reason = "needs_review", "redirect_limit_or_missing_location"
                    break
                redirected = urllib.parse.urljoin(current, sample.location)
                target = validate_endpoint(redirected)
                if original.scheme == "https" and target.scheme == "http":
                    verdict, reason = "needs_review", "tls_downgrade"
                    break
                current = redirected
                redirects += 1
                continue
            if sample.status not in (200, 206):
                verdict, reason = "needs_review", "http_not_successful"
                break
            verdict, reason = classify_sample(sample.body[:MAX_BYTES], sample.content_type)
            if verdict == "playlist_pending":
                hint = playlist_hint(
                    sample.body[:MAX_BYTES], sample.content_type, current)
                if hint.kind == "playlist_single_target" and hint.target is not None:
                    if playlist_follows >= 1 or redirects >= MAX_REDIRECTS:
                        verdict, reason = "playlist_pending", "playlist_chain_limit"
                    else:
                        target = validate_endpoint(hint.target)
                        if original.scheme == "https" and target.scheme == "http":
                            verdict, reason = "needs_review", "tls_downgrade"
                        else:
                            playlist_follows += 1
                            redirects += 1
                            current = hint.target
                            continue
                else:
                    verdict, reason = "playlist_pending", hint.kind
            report = {
                "verdict": verdict, "reason": reason, "formatHint": reason,
                "redirectCount": redirects, "sampleBytes": min(MAX_BYTES, len(sample.body)),
                "streamSha256": fingerprint,
            }
            if sample.continuity is not None:
                report["continuityEvidence"] = sample.continuity
            return report
    except UnsafeEndpoint as error:
        verdict, reason = "blocked_unsafe", str(error)
    except (OSError, ssl.SSLError, http.client.HTTPException,
            TimeoutError, ValueError) as error:
        verdict, reason = "needs_review", "connection_or_protocol_error"
    return {
        "verdict": verdict, "reason": reason, "formatHint": "",
        "redirectCount": redirects, "sampleBytes": 0, "streamSha256": fingerprint,
    }


def probe_candidates(
    discovery: dict, request: Callable[[str], ResponseSample], *, limit: int = 3,
    observation_day: dt.date | None = None,
) -> dict:
    """Probe a bounded number of candidates. Always preview, never publish."""
    if not isinstance(discovery, dict) or discovery.get("schemaVersion") != 1 or (
        discovery.get("publicationAllowed") is not False) or not isinstance(
            discovery.get("candidates"), list):
        raise ValueError("Untrusted discovery input")
    if not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("Probe budget exceeded")
    items = discovery["candidates"]
    if len(items) > 20000:
        raise ValueError("Excessive candidate count")
    if observation_day is None:
        observation_day = dt.datetime.now(dt.timezone.utc).date()
    rows: list[dict] = []
    ids: set[str] = set()
    eligible: list[tuple[str, str]] = []
    for station in items:
        if not isinstance(station, dict):
            raise ValueError("Invalid candidate entry")
        value = station.get("stationuuid")
        try:
            identifier = str(uuid.UUID(value)) if isinstance(value, str) else ""
        except ValueError:
            identifier = ""
        if not identifier or identifier in ids:
            raise ValueError("Invalid or duplicated candidate UUID")
        ids.add(identifier)
        status = station.get("status")
        if status not in ("candidate_requires_qualification",
                          "needs_stream_check", "needs_duplicate_review"):
            raise ValueError("Unexpected candidate status")
        if status == "needs_duplicate_review":
            continue
        raw_url = station.get("streamUrl")
        if isinstance(raw_url, str) and raw_url:
            eligible.append((identifier, raw_url))
    # Do not re-check the first N UUIDs forever: rotate the network probe
    # window by UTC date. This stays bounded even when hundreds of stations
    # are discovered and cannot reorder a user's historical radio catalog.
    eligible.sort()
    if eligible:
        start = (observation_day.toordinal() * limit) % len(eligible)
        selected = [eligible[(start + i) % len(eligible)]
                    for i in range(min(limit, len(eligible)))]
    else:
        selected = []
    for identifier, raw_url in selected:
        check = probe_url(raw_url, request)
        rows.append({"stationuuid": identifier, **check, "publicationAllowed": False})
    return {
        "schemaVersion": 1,
        "observationDate": observation_day.isoformat(),
        "publicationAllowed": False,
        "checkedCount": len(rows),
        "audioEvidenceCount": sum(x["verdict"] == "audio_sample_ok" for x in rows),
        "sustainedTransportEvidenceCount": sum(
            x.get("continuityEvidence", {}).get("state") == "transport_sustained"
            for x in rows),
        "technicalVerifiedCount": 0,
        "checks": rows,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--allow-network", action="store_true",
                   help="Required for any external stream request; use only on controlled runners.")
    p.add_argument("--extended-continuity", action="store_true",
                   help="Observe at most 10 s and 512 KiB per apparent audio stream; "
                        "NOT decoder or publisher approval.")
    args = p.parse_args(argv)
    if not args.allow_network:
        p.error("Network probing disabled: --allow-network is mandatory")
    if args.discovery.stat().st_size > MAX_INPUT_SIZE:
        p.error("Discovery document too large")
    data = json.loads(args.discovery.read_text(encoding="utf-8"))
    report = probe_candidates(
        data,
        PinnedHttpTransport(extended_continuity=args.extended_continuity).request,
        limit=args.limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"STREAM_PROBE_PREVIEW_ONLY samples={report['checkedCount']} "
          f"audio_evidence={report['audioEvidenceCount']} "
          f"sustained_transport={report['sustainedTransportEvidenceCount']} "
          "technical_verified=0 published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
