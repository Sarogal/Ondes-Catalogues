#!/usr/bin/env python3
"""Opt-in, conservative HLS segment evidence; NO automatic radio approval.

Plan one segment from a fully observed LIVE media manifest, optionally via
ONE safe same-origin master variant. Never choose among multiple renditions,
open keys/maps, follow redirects or disclose source/segment URLs.
A segment can be video-only or from a recording: structural evidence is not
proof of audible live radio. The network caller must use pinned HTTPS/HTTP.
"""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable

from radio_hls_manifest_evidence import inspect_hls_manifest, MAX_HLS_BYTES
from radio_stream_frame_chain import analyze_frame_chain
from radio_stream_technical_probe import (
    PinnedHttpTransport, ResponseSample, UnsafeEndpoint, validate_endpoint,
)

SEGMENT_BYTES = 16384
ALLOWED_SEGMENT_EXTENSIONS = (".ts", ".aac", ".mp3")


@dataclass(frozen=True)
class SegmentPlan:
    # Internal-only; never serialize this object or show URLs in a report.
    url: str


def plan_one_segment(manifest: bytes, content_type: str, source_url: str) -> SegmentPlan | None:
    """Fail closed unless the manifest is complete, simple and same-origin."""
    verdict = inspect_hls_manifest(manifest, content_type, source_url)
    if verdict["kind"] != "live_manifest_candidate":
        return None
    original = validate_endpoint(source_url)
    lines = [line.strip() for line in manifest.decode("utf-8-sig").splitlines()]
    segments = [line for line in lines if line and not line.startswith("#")]
    # Use last segment to maximize availability. One segment max; no variant.
    value = segments[-1]
    if (len(value) > 200 or any(ord(ch) < 33 or ord(ch) > 126 for ch in value)
        or "\\" in value or "#" in value or "@" in value or "{" in value or "}" in value
        or value.startswith(("//", "/", "?")) or "://" in value):
        return None
    reference = urllib.parse.urlsplit(value)
    if reference.scheme or reference.netloc or reference.fragment:
        return None
    # Neither encoded nor literal traversal is allowed, including double encoding.
    decoded = urllib.parse.unquote(urllib.parse.unquote(reference.path))
    if any(part in (".", "..") for part in decoded.split("/")):
        return None
    if not decoded.lower().endswith(ALLOWED_SEGMENT_EXTENSIONS):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_./%+~-]+", reference.path):
        return None
    # Permit bounded token queries, never fragments, controls, embedded credentials.
    if reference.query and not re.fullmatch(r"[A-Za-z0-9_=&%+./~-]{1,128}", reference.query):
        return None
    target = urllib.parse.urljoin(source_url, value)
    resolved = validate_endpoint(target)
    if (resolved.scheme != original.scheme or resolved.hostname != original.hostname
        or (resolved.port or (443 if resolved.scheme == "https" else 80))
        != (original.port or (443 if original.scheme == "https" else 80))):
        return None
    return SegmentPlan(url=target)


def plan_single_variant(master: bytes, content_type: str,
                        source_url: str) -> SegmentPlan | None:
    """Only ONE master rendition may be followed, with the same-origin guard."""
    hint = inspect_hls_manifest(master, content_type, source_url)
    if hint["kind"] != "master_single_variant_pending":
        return None
    lines = [line.strip() for line in master.decode("utf-8-sig").splitlines()]
    references = [line for line in lines if line and not line.startswith("#")]
    if len(references) != 1:
        return None
    value = references[0]
    if (len(value) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in value)
        or "\\" in value or "#" in value or "@" in value or "{" in value
        or "}" in value or value.startswith(("//", "/", "?"))
        or "://" in value):
        return None
    ref = urllib.parse.urlsplit(value)
    if ref.scheme or ref.netloc or ref.fragment:
        return None
    unquoted = urllib.parse.unquote(urllib.parse.unquote(ref.path))
    if (not unquoted.lower().endswith(".m3u8") or
            any(part in (".", "..") for part in unquoted.split("/")) or
            not re.fullmatch(r"[A-Za-z0-9_./%+~-]+", ref.path) or
            (ref.query and not re.fullmatch(
                r"[A-Za-z0-9_=&%+./~-]{1,128}", ref.query))):
        return None
    original = validate_endpoint(source_url)
    target = urllib.parse.urljoin(source_url, value)
    parsed = validate_endpoint(target)
    if (parsed.scheme != original.scheme or parsed.hostname != original.hostname or
            (parsed.port or (443 if parsed.scheme == "https" else 80))
            != (original.port or (443 if original.scheme == "https" else 80))):
        return None
    return SegmentPlan(url=target)


def mpeg_ts_packets(sample: bytes) -> dict:
    """Bounded TS transport evidence, not an audio codec verification."""
    proof = {"state": "not_confirmed", "packetCount": 0,
             "publicationAllowed": False}
    if not isinstance(sample, bytes) or len(sample) > SEGMENT_BYTES or len(sample) < 188 * 4:
        return proof
    # Require four aligned complete non-null TS packets, not one coincidental sync.
    non_null = 0
    for pos in range(0, len(sample) - 187, 188):
        a, b, c, d = sample[pos:pos + 4]
        if a != 0x47 or b & 0x80 or (d & 0x30) == 0:
            break
        if ((b & 0x1F) << 8 | c) != 0x1FFF:
            non_null += 1
        proof["packetCount"] += 1
    if proof["packetCount"] >= 4 and non_null >= 4:
        proof["state"] = "mpeg_ts_structure"
    return proof


def inspect_segment_bytes(sample: bytes) -> dict:
    result = {"state": "not_confirmed", "codecHint": "unconfirmed",
              "bytesObserved": min(len(sample), SEGMENT_BYTES) if isinstance(sample, bytes) else 0,
              "publicationAllowed": False}
    if not isinstance(sample, bytes) or not 1 <= len(sample) <= SEGMENT_BYTES:
        return result
    frames = analyze_frame_chain(sample)
    if frames["state"] == "frame_chain":
        result["state"] = "audio_frame_chain"
        result["codecHint"] = frames["codec"]
        return result
    ts = mpeg_ts_packets(sample)
    if ts["state"] == "mpeg_ts_structure":
        result["state"] = "mpeg_ts_structure_only"
        result["codecHint"] = "mpegts_unverified_audio"
        result["packetCount"] = ts["packetCount"]
    return result


def verify_one_segment(
    manifest_url: str,
    request_manifest: Callable[[str], ResponseSample],
    request_segment: Callable[[str], ResponseSample],
) -> dict:
    """Request at most ONE same-origin segment, fail closed on redirects."""
    output = {"state": "not_confirmed", "segmentEvidence": None,
              "manifestKind": "unconfirmed", "childManifestKind": "not_followed",
              "publicationAllowed": False, "technicalQualified": False}
    try:
        validate_endpoint(manifest_url)
        manifest_response = request_manifest(manifest_url)
        if manifest_response.status != 200:
            output["state"] = "manifest_fetch_incomplete"
            return output
        content_type = manifest_response.content_type
        manifest_data = manifest_response.body
        manifest_verdict = inspect_hls_manifest(manifest_data, content_type, manifest_url)
        output["manifestKind"] = manifest_verdict["kind"]
        plan = plan_one_segment(manifest_data, content_type, manifest_url)
        if plan is None and manifest_verdict["kind"] == "master_single_variant_pending":
            # One child media playlist maximum. Never auto-pick a quality.
            child_plan = plan_single_variant(manifest_data, content_type, manifest_url)
            if child_plan is None:
                output["state"] = "no_safe_single_variant"
                return output
            child = request_manifest(child_plan.url)
            if child.status != 200:
                output["state"] = "child_manifest_fetch_incomplete"
                return output
            output["childManifestKind"] = inspect_hls_manifest(
                child.body, child.content_type, child_plan.url)["kind"]
            plan = plan_one_segment(child.body, child.content_type, child_plan.url)
            if plan is None:
                output["state"] = "child_not_simple_live_media"
                return output
        if plan is None:
            output["state"] = "no_safe_simple_segment"
            return output
        segment_response = request_segment(plan.url)
        # No redirects: even an originally same-origin segment might redirect to
        # an unsafe destination. This also prevents SSRF via untrusted CDN hops.
        if segment_response.status not in (200, 206):
            output["state"] = "segment_http_unconfirmed"
            return output
        content_mime = segment_response.content_type.split(";", 1)[0].strip().lower()
        if content_mime in {
            "text/html", "text/plain", "application/json",
            "application/xml", "text/xml", "application/vnd.apple.mpegurl",
        }:
            output["state"] = "segment_non_audio_mime"
            return output
        evidence = inspect_segment_bytes(segment_response.body)
        output["segmentEvidence"] = evidence
        output["state"] = (
            "segment_structural_evidence" if evidence["state"] != "not_confirmed"
            else "segment_unrecognized"
        )
        return output
    except (UnsafeEndpoint, ValueError, OSError, TimeoutError) as error:
        output["state"] = "unsafe_or_failed_segment_request"
        return output


def safe_segment_transport() -> PinnedHttpTransport:
    """A separate DNS-pinned, bounded-range transport for segment bytes."""
    return PinnedHttpTransport(segment_mode=True)
